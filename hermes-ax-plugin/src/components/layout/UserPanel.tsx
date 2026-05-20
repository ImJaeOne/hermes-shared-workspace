import React, { useState } from "react";
import { getApiErrorMessage, isUnauthorizedError } from "../../api/client";
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
    login,
    logout,
    refreshAll,
  } = useApp();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleLogin = async () => {
    if (!username.trim() || !password) return;
    setSubmitting(true);
    setError("");
    try {
      await login({ username: username.trim(), password });
      await refreshAll();
      onClose();
    } catch (e) {
      setError(isUnauthorizedError(e) ? "아이디 또는 비밀번호를 확인해주세요." : getApiErrorMessage(e, "로그인에 실패했습니다."));
    } finally {
      setSubmitting(false);
    }
  };

  const handleLogout = async () => {
    setSubmitting(true);
    setError("");
    try {
      await logout();
      await refreshAll();
      onClose();
    } catch (e) {
      setError(getApiErrorMessage(e, "로그아웃에 실패했습니다."));
    } finally {
      setSubmitting(false);
    }
  };

  const expiresAtLabel = authExpiresAt ? new Date(authExpiresAt).toLocaleString("ko-KR") : null;

  return (
    <div className="ax-overlay" onClick={onClose}>
      <div className="ax-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="ax-dialog-header">
          <h2>{authenticated ? "세션 정보" : "로그인"}</h2>
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
            </div>
          ) : (
            <>
              <label className="ax-label">
                아이디
                <input
                  className="ax-input"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="username"
                  autoFocus
                  onKeyDown={(e) => e.key === "Enter" && handleLogin()}
                />
              </label>
              <label className="ax-label">
                비밀번호
                <input
                  className="ax-input"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="password"
                  onKeyDown={(e) => e.key === "Enter" && handleLogin()}
                />
              </label>
              <p className="ax-hint">로그인하면 코멘트, 승인, 산출물 추가 등 쓰기 작업을 사용할 수 있습니다.</p>
            </>
          )}
          {error && <p className="ax-form-error">{error}</p>}
        </div>
        <div className="ax-dialog-footer">
          <button className="ax-btn ax-btn-ghost" onClick={onClose}>닫기</button>
          {authenticated ? (
            <button className="ax-btn ax-btn-primary" onClick={handleLogout} disabled={submitting || authLoading}>
              {submitting || authLoading ? "처리 중..." : "로그아웃"}
            </button>
          ) : (
            <button className="ax-btn ax-btn-primary" onClick={handleLogin} disabled={!username.trim() || !password || submitting || authLoading}>
              {submitting || authLoading ? "로그인 중..." : "로그인"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
