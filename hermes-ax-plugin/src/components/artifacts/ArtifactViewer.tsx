import React from "react";
import type { Artifact } from "../../types/models";
import { getArtifactFileUrl } from "../../api/client";

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

  if (!content && !artifact.file_path) {
    return <div className="ax-artifact-viewer ax-artifact-empty">내용 없음</div>;
  }

  // Image types - render as img
  if (effectiveMime.startsWith("image/")) {
    return (
      <div className="ax-artifact-viewer">
        <img
          src={getArtifactFileUrl(id)}
          alt={artifact.title}
          className="ax-artifact-image"
        />
      </div>
    );
  }

  // HTML - render in sandboxed iframe
  if (effectiveMime === "text/html") {
    return (
      <div className="ax-artifact-viewer">
        <iframe
          srcDoc={content}
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
      {artifact.file_path && (
        <a href={getArtifactFileUrl(id)} download className="ax-btn ax-btn-ghost ax-btn-sm">
          파일 다운로드
        </a>
      )}
    </div>
  );
}
