import React, { useState } from "react";
import { getApiErrorMessage } from "../../api/client";
import { useApp } from "../../context/AppContext";

interface Props {
  onClose: () => void;
}

export function UserPanel({ onClose }: Props) {
  const {
    authUser,
    authExpiresAt,
    authenticated,
    authLoading,
    currentUserLabel,
    refreshAll,
  } = useApp();
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleRefresh = async () => {
    setSubmitting(true);
    setError("");
    try {
      await refreshAll();
    } catch (e) {
      setError(getApiErrorMessage(e, "세션 정보를 새로고침하지 못했습니다."));
    } finally {
      setSubmitting(false);
    }
  };

  const expiresAtLabel = authExpiresAt ? new Date(authExpiresAt).toLocaleString("ko-KR") : null;

  return (
    <div className="ax-overlay" onClick={onClose}>
      <div className="ax-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="ax-dialog-header">
          <h2>대시보드 세션</h2>
        </div>
        <div className="ax-dialog-body">
          {authenticated && authUser ? (
            <div className="ax-auth-session-card">
              <div className="ax-auth-session-row">
                <span className="ax-auth-session-label">표시 이름</span>
                <strong>{currentUserLabel}</strong>
              </div>
              <div className="ax-auth-session-row">
                <span className="ax-auth-session-label">계정</span>
                <span>{authUser.username}</span>
              </div>
              <div className="ax-auth-session-row">
                <span className="ax-auth-session-label">역할</span>
                <span>{authUser.role}</span>
              </div>
              {expiresAtLabel && (
                <div className="ax-auth-session-row">
                  <span className="ax-auth-session-label">세션 만료</span>
                  <span>{expiresAtLabel}</span>
                </div>
              )}
              <p className="ax-hint">
                AX는 별도 로그인을 사용하지 않습니다. 인증은 상위 Hermes Dashboard 세션에서 관리됩니다.
              </p>
            </div>
          ) : (
            <div className="ax-auth-session-card">
              <p className="ax-hint">
                상위 Hermes Dashboard 세션을 확인할 수 없습니다. 대시보드에서 인증한 뒤 AX를 다시 열어주세요.
              </p>
            </div>
          )}
          {error && <p className="ax-form-error">{error}</p>}
        </div>
        <div className="ax-dialog-footer">
          <button className="ax-btn ax-btn-ghost" onClick={onClose}>닫기</button>
          <button className="ax-btn ax-btn-primary" onClick={handleRefresh} disabled={submitting || authLoading}>
            {submitting || authLoading ? "확인 중..." : "세션 새로고침"}
          </button>
        </div>
      </div>
    </div>
  );
}
