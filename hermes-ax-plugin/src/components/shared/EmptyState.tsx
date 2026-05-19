import React from "react";

interface Props {
  message: string;
  action?: React.ReactNode;
}

export function EmptyState({ message, action }: Props) {
  return (
    <div className="ax-empty">
      <p>{message}</p>
      {action}
    </div>
  );
}
