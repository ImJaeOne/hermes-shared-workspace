import React, { useState } from "react";
import type { Comment } from "../../types/models";
import { useApp } from "../../context/AppContext";
import { createComment, getApiErrorMessage } from "../../api/client";
import { CommentItem } from "./CommentItem";

interface Props {
  artifactId: string;
  comments: Comment[];
  onRefresh: () => void;
}

export function CommentSection({ artifactId, comments, onRefresh }: Props) {
  const { authenticated, currentUserLabel, authUser } = useApp();
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!body.trim() || !authenticated) return;
    setSubmitting(true);
    setError("");
    try {
      await createComment(artifactId, {
        author: currentUserLabel || authUser?.username || "user",
        body: body.trim(),
      });
      setBody("");
      onRefresh();
    } catch (e) {
      setError(getApiErrorMessage(e, "코멘트를 등록하지 못했습니다."));
      console.error("Failed to add comment:", e);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="ax-comments">
      <h4 className="ax-comments-title">코멘트 ({comments.length})</h4>

      {comments.length > 0 && (
        <div className="ax-comment-list">
          {comments.map((c) => (
            <CommentItem key={c.id} comment={c} onRefresh={onRefresh} />
          ))}
        </div>
      )}

      <div className="ax-comment-form">
        {!authenticated ? (
          <p className="ax-auth-required">로그인 후 코멘트를 남길 수 있습니다.</p>
        ) : (
          <>
            <textarea
              className="ax-textarea ax-comment-input"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="코멘트를 작성하세요..."
              rows={2}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSubmit();
              }}
            />
            <div className="ax-comment-form-actions">
              <span className="ax-hint">Cmd+Enter로 전송</span>
              <button
                className="ax-btn ax-btn-primary ax-btn-sm"
                onClick={handleSubmit}
                disabled={!body.trim() || submitting}
              >
                {submitting ? "전송 중..." : "전송"}
              </button>
            </div>
          </>
        )}
        {error && <p className="ax-form-error">{error}</p>}
      </div>
    </div>
  );
}
