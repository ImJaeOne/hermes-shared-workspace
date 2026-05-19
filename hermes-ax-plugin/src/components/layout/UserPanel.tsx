import React, { useState } from "react";
import { useApp } from "../../context/AppContext";

interface Props {
  onClose: () => void;
}

export function UserPanel({ onClose }: Props) {
  const { username, setUsername } = useApp();
  const [value, setValue] = useState(username);

  const handleSave = () => {
    setUsername(value.trim());
    onClose();
  };

  return (
    <div className="ax-overlay" onClick={onClose}>
      <div className="ax-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="ax-dialog-header">
          <h2>사용자 설정</h2>
        </div>
        <div className="ax-dialog-body">
          <label className="ax-label">
            사용자명
            <input
              className="ax-input"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="이름을 입력하세요..."
              autoFocus
              onKeyDown={(e) => e.key === "Enter" && handleSave()}
            />
          </label>
          <p className="ax-hint">산출물에 코멘트를 남길 때 사용됩니다.</p>
        </div>
        <div className="ax-dialog-footer">
          <button className="ax-btn ax-btn-ghost" onClick={onClose}>취소</button>
          <button className="ax-btn ax-btn-primary" onClick={handleSave}>저장</button>
        </div>
      </div>
    </div>
  );
}
