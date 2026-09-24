import styles from "@/app/applications/business-analysis/business-analysis.module.css";

type Message = { role: "user" | "assistant"; content: string };

export function AnalysisMessageList({ messages }: { messages: Message[] }) {
  if (messages.length === 0) return null;
  return <div className={styles.messageList}>{messages.map((message, index) => <div className={message.role === "user" ? styles.userMessage : styles.assistantMessage} key={`${message.role}-${index}`}><span className={styles.messageRole}>{message.role === "user" ? "你" : "Agent"}</span><p>{message.content}</p></div>)}</div>;
}
