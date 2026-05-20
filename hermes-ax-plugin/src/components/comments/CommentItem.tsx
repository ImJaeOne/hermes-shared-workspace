import React, { useMemo, useState } from "react";
import type { Comment } from "../../types/models";
import { useApp } from "../../context/AppContext";
import { deleteComment, getApiErrorMessage, updateComment } from "../../api/client";

interface Props {
  comment: Comment;
  onRefresh: () => void;
}

export function CommentItem({ comment, onRefresh }: Props) {
  const { authUser } = useApp();
  const [editing, setEditing] = useState(false);
  const [editBody, setEditBody] = useState(comment.body);
  const [error, setError] = useState("");

  const isOwn = useMemo(() => {
    if (!authUser) return false;
    if (comment.author_user_id && authUser.id) {
      return comment.author_user_id === authUser.id;
    }
    return [authUser.username, authUser.display_name].filter(Boolean).includes(comment.author);
  }, [authUser, comment.author, comment.author_user_id]);

  const handleUpdate = async () => {
    if (!editBody.trim()) return;
    setError("");
    try {
      await updateComment(comment.id, { body: editBody.trim() });
      setEditing(false);
      onRefresh();
    } catch (e) {
      setError(getApiErrorMessage(e, "코멘트를 수정하지 못했습니다."));
      console.error("Failed to update comment:", e);
    }
  };

  const handleDelete = async () => {
    setError("");
    try {
      await deleteComment(comment.id);
      onRefresh();
    } catch (e) {
      setError(getApiErrorMessage(e, "코멘트를 삭제하지 못했습니다."));
      console.error("Failed to delete comment:", e);
    }
  };

  const timeStr = (() => {
    try {
      return new Date(comment.created_at).toLocaleString("ko-KR");
    } catch {
      return "";
    }
  })();

  return (
    <div className="ax-comment-item">
      <div className="ax-comment-header">
        <span className="ax-comment-author">{comment.author}</span>
        <span className="ax-comment-time">{timeStr}</span>
        {isOwn && !editing && (
          <div className="ax-comment-actions">
            <button className="ax-btn ax-btn-ghost ax-btn-xs" onClick={() => setEditing(true)}>수정</button>
            <button className="ax-btn ax-btn-ghost ax-btn-xs" onClick={handleDelete}>삭제</button>
          </div>
        )}
      </div>
      {editing ? (
        <div className="ax-comment-edit">
          <textarea
            className="ax-textarea"
            value={editBody}
            onChange={(e) => setEditBody(e.target.value)}
            rows={2}
          />
          <div className="ax-comment-edit-actions">
            <button className="ax-btn ax-btn-ghost ax-btn-xs" onClick={() => { setEditing(false); setEditBody(comment.body); setError(""); }}>취소</button>
            <button className="ax-btn ax-btn-primary ax-btn-xs" onClick={handleUpdate}>저장</button>
          </div>
        </div>
      ) : (
        <p className="ax-comment-body">{comment.body}</p>
      )}
      {error && <p className="ax-form-error">{error}</p>}
    </div>
  );
}
