import type { ReactNode } from "react";

interface MessageContentProps {
  content: string;
  className?: string;
}

const LIST_ITEM = /^(?:[-•]\s+|\d+[.)]\s+)(.+)$/;

/** Render the assistant's safe plain-text bullets as a semantic, scannable list. */
export function MessageContent({ content, className = "" }: MessageContentProps) {
  const nodes: ReactNode[] = [];
  let listItems: string[] = [];

  const flushList = () => {
    if (listItems.length === 0) return;
    const items = listItems;
    listItems = [];
    nodes.push(
      <ul className="message-content-list" key={`list-${nodes.length}`}>
        {items.map((item, index) => (
          <li key={`${index}-${item}`}>{item}</li>
        ))}
      </ul>,
    );
  };

  for (const rawLine of content.replace(/\r\n/g, "\n").split("\n")) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      continue;
    }

    const item = line.match(LIST_ITEM);
    if (item) {
      listItems.push(item[1]);
      continue;
    }

    flushList();
    nodes.push(<p key={`paragraph-${nodes.length}`}>{line}</p>);
  }
  flushList();

  return <div className={`message-content ${className}`.trim()}>{nodes}</div>;
}
