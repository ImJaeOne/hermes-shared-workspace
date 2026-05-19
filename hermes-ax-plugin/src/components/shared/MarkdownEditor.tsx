import React, { useState } from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
}

/** Lightweight regex-based MD→HTML for preview. */
function renderMarkdown(md: string): string {
  let html = md
    // Code blocks
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="ax-md-code"><code>$2</code></pre>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code class="ax-md-inline-code">$1</code>')
    // Headings
    .replace(/^#### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    // Bold + Italic
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    // Unordered list
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    // Ordered list
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    // Checkbox
    .replace(/^- \[x\] (.+)$/gm, '<li>&#9745; $1</li>')
    .replace(/^- \[ \] (.+)$/gm, '<li>&#9744; $1</li>')
    // Horizontal rule
    .replace(/^---$/gm, '<hr />')
    // Tables (simple)
    .replace(/\|(.+)\|/g, (match) => {
      if (match.match(/^\|[\s-|]+\|$/)) return '';
      const cells = match.split('|').filter(Boolean).map(c => c.trim());
      return '<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>';
    })
    // Paragraphs (double newline)
    .replace(/\n\n/g, '</p><p>')
    // Single newlines to <br>
    .replace(/\n/g, '<br />');

  // Wrap loose <li> in <ul>
  html = html.replace(/((?:<li>.*?<\/li>\s*)+)/g, '<ul>$1</ul>');
  // Wrap loose <tr> in <table>
  html = html.replace(/((?:<tr>.*?<\/tr>\s*)+)/g, '<table class="ax-md-table">$1</table>');

  return `<p>${html}</p>`;
}

export function MarkdownEditor({ value, onChange, placeholder, rows = 12 }: Props) {
  const [preview, setPreview] = useState(false);

  return (
    <div className="ax-md-editor">
      <div className="ax-md-editor-toolbar">
        <button
          type="button"
          className={`ax-btn ax-btn-xs ${!preview ? 'ax-btn-primary' : 'ax-btn-ghost'}`}
          onClick={() => setPreview(false)}
        >
          편집
        </button>
        <button
          type="button"
          className={`ax-btn ax-btn-xs ${preview ? 'ax-btn-primary' : 'ax-btn-ghost'}`}
          onClick={() => setPreview(true)}
        >
          미리보기
        </button>
      </div>
      {preview ? (
        <div
          className="ax-md-preview"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(value || '') }}
        />
      ) : (
        <textarea
          className="ax-textarea ax-md-textarea"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={rows}
        />
      )}
    </div>
  );
}
