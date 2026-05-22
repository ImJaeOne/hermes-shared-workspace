import React, { useEffect, useState } from "react";
import type { Artifact } from "../../types/models";
import { createArtifactObjectUrl, downloadArtifactFile, getApiErrorMessage } from "../../api/client";

interface Props {
  artifact: Artifact;
}

/** Lightweight regex-based MD→HTML renderer. */
function renderMarkdown(md: string): string {
  let html = md
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="ax-md-code"><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code class="ax-md-inline-code">$1</code>')
    .replace(/^#### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/^- \[x\] (.+)$/gm, '<li>&#9745; $1</li>')
    .replace(/^- \[ \] (.+)$/gm, '<li>&#9744; $1</li>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    .replace(/^---$/gm, '<hr />')
    .replace(/\|(.+)\|/g, (match) => {
      if (match.match(/^\|[\s-|]+\|$/)) return '';
      const cells = match.split('|').filter(Boolean).map(c => c.trim());
      return '<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>';
    })
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br />');

  html = html.replace(/((?:<li>.*?<\/li>\s*)+)/g, '<ul>$1</ul>');
  html = html.replace(/((?:<tr>.*?<\/tr>\s*)+)/g, '<table class="ax-md-table">$1</table>');

  return `<p>${html}</p>`;
}

export function ArtifactViewer({ artifact }: Props) {
  const { content, mime_type, content_type, id } = artifact;
  const effectiveMime = mime_type || content_type || "text/plain";
  const hasFile = Boolean(artifact.storage_key || artifact.file_path);
  const [objectUrl, setObjectUrl] = useState("");
  const [fileError, setFileError] = useState("");
  const [downloadError, setDownloadError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let nextUrl = "";
    const shouldFetchBlob = hasFile && (
      effectiveMime.startsWith("image/") ||
      effectiveMime === "application/pdf" ||
      (effectiveMime === "text/html" && !content)
    );

    setObjectUrl("");
    setFileError("");
    setDownloadError("");
    if (!shouldFetchBlob) return undefined;

    void createArtifactObjectUrl(id)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        nextUrl = url;
        setObjectUrl(url);
      })
      .catch((error) => {
        if (!cancelled) {
          setFileError(getApiErrorMessage(error, "파일 미리보기를 불러오지 못했습니다."));
        }
      });

    return () => {
      cancelled = true;
      if (nextUrl) URL.revokeObjectURL(nextUrl);
    };
  }, [content, effectiveMime, hasFile, id]);

  if (!content && !hasFile) {
    return <div className="ax-artifact-viewer ax-artifact-empty">내용 없음</div>;
  }

  // Image types - render as img
  if (effectiveMime.startsWith("image/")) {
    return (
      <div className="ax-artifact-viewer">
        {fileError ? (
          <p className="ax-form-error">{fileError}</p>
        ) : objectUrl ? (
          <img
            src={objectUrl}
            alt={artifact.title}
            className="ax-artifact-image"
          />
        ) : (
          <div className="ax-artifact-empty">이미지 미리보기를 불러오는 중입니다...</div>
        )}
      </div>
    );
  }

  // PDF - render in sandboxed iframe from blob URL so custom auth headers work.
  if (effectiveMime === "application/pdf") {
    return (
      <div className="ax-artifact-viewer">
        {fileError ? (
          <p className="ax-form-error">{fileError}</p>
        ) : objectUrl ? (
          <iframe
            src={objectUrl}
            sandbox="allow-same-origin"
            className="ax-artifact-iframe"
            title={artifact.title}
          />
        ) : (
          <div className="ax-artifact-empty">PDF 미리보기를 불러오는 중입니다...</div>
        )}
      </div>
    );
  }

  // HTML - render in sandboxed iframe
  if (effectiveMime === "text/html") {
    return (
      <div className="ax-artifact-viewer">
        <iframe
          {...(content ? { srcDoc: content } : { src: objectUrl })}
          sandbox="allow-same-origin"
          className="ax-artifact-iframe"
          title={artifact.title}
        />
      </div>
    );
  }

  // JSON
  if (effectiveMime === "application/json") {
    let formatted: string;
    try {
      formatted = JSON.stringify(JSON.parse(content), null, 2);
    } catch {
      formatted = content;
    }
    return (
      <div className="ax-artifact-viewer">
        <pre className="ax-artifact-json">{formatted}</pre>
      </div>
    );
  }

  // Markdown - render with lightweight parser
  if (effectiveMime === "text/markdown") {
    return (
      <div className="ax-artifact-viewer">
        <div
          className="ax-artifact-markdown"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
        />
      </div>
    );
  }

  // Plain text
  if (effectiveMime === "text/plain") {
    return (
      <div className="ax-artifact-viewer">
        <pre className="ax-artifact-text">{content}</pre>
      </div>
    );
  }

  // Unsupported type - show download link
  return (
    <div className="ax-artifact-viewer ax-artifact-unsupported">
      <p>지원되지 않는 형식: {effectiveMime}</p>
      {hasFile && (
        <button
          type="button"
          className="ax-btn ax-btn-ghost ax-btn-sm"
          onClick={() => {
            setDownloadError("");
            void downloadArtifactFile(id, artifact.original_filename || artifact.title || id)
              .catch((error) => setDownloadError(getApiErrorMessage(error, "파일을 다운로드하지 못했습니다.")));
          }}
        >
          파일 다운로드
        </button>
      )}
      {downloadError && <p className="ax-form-error">{downloadError}</p>}
    </div>
  );
}
