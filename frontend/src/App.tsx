import { useCallback, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

type Role = "user" | "assistant";

type ChatMessage = {
  role: Role;
  content: string;
  codeBlocks?: string[];
  images?: string[];
  toolResults?: string[];
};

type StreamEvent =
  | { type: "start"; session_id: string }
  | { type: "llm_token"; text: string }
  | { type: "tool_code"; name: string; code: string }
  | { type: "tool_result"; text: string }
  | { type: "figures"; images: string[] }
  | { type: "done" }
  | { type: "error"; message: string };

function parseSseBlocks(buffer: string): { events: StreamEvent[]; rest: string } {
  const events: StreamEvent[] = [];
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  for (const block of parts) {
    const line = block.trim();
    if (!line.startsWith("data: ")) continue;
    try {
      events.push(JSON.parse(line.slice(6)) as StreamEvent);
    } catch {
      /* ignore */
    }
  }
  return { events, rest };
}

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [previewText, setPreviewText] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const assistantIdxRef = useRef<number>(-1);

  const mdComponents = useMemo(
    () => ({
      code({
        className,
        children,
        inline,
        ...props
      }: {
        className?: string;
        children?: ReactNode;
        inline?: boolean;
      }) {
        const match = /language-(\w+)/.exec(className || "");
        const code = String(children).replace(/\n$/, "");
        if (inline || !match) {
          return (
            <code className={className} {...props}>
              {children}
            </code>
          );
        }
        return (
          <SyntaxHighlighter
            style={oneDark}
            language={match[1]}
            PreTag="div"
            customStyle={{ margin: 0, borderRadius: 8 }}
          >
            {code}
          </SyntaxHighlighter>
        );
      },
    }),
    []
  );

  const onUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setStatus("上传中…");
    const fd = new FormData();
    fd.append("file", f);
    try {
      const res = await fetch("/api/upload", { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setSessionId(data.session_id);
      setPreviewText(JSON.stringify(data.preview, null, 2));
      setMessages([]);
      setStatus(`已上传：${data.filename}`);
    } catch (err) {
      setStatus(`上传失败：${String(err)}`);
    }
    e.target.value = "";
  };

  const patchAssistant = useCallback((fn: (m: ChatMessage) => ChatMessage) => {
    setMessages((prev) => {
      const i = assistantIdxRef.current;
      if (i < 0 || i >= prev.length) return prev;
      const next = [...prev];
      next[i] = fn(next[i]);
      return next;
    });
  }, []);

  const runStream = useCallback(
    async (sid: string, userText: string) => {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sid, message: userText }),
      });
      if (!res.ok || !res.body) {
        throw new Error(await res.text());
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";

      setMessages((prev) => {
        const next: ChatMessage[] = [
          ...prev,
          { role: "user", content: userText },
          {
            role: "assistant",
            content: "",
            codeBlocks: [],
            images: [],
            toolResults: [],
          },
        ];
        assistantIdxRef.current = next.length - 1;
        return next;
      });

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const { events, rest } = parseSseBlocks(buf);
        buf = rest;
        for (const ev of events) {
          if (ev.type === "llm_token") {
            patchAssistant((m) => ({ ...m, content: m.content + ev.text }));
          } else if (ev.type === "tool_code") {
            patchAssistant((m) => ({
              ...m,
              codeBlocks: [...(m.codeBlocks || []), ev.code],
            }));
          } else if (ev.type === "tool_result") {
            patchAssistant((m) => ({
              ...m,
              toolResults: [...(m.toolResults || []), ev.text],
            }));
          } else if (ev.type === "figures") {
            patchAssistant((m) => ({
              ...m,
              images: [...(m.images || []), ...ev.images],
            }));
          } else if (ev.type === "error") {
            setStatus(`错误：${ev.message}`);
            patchAssistant((m) => ({
              ...m,
              content: m.content + `\n\n**错误：** ${ev.message}`,
            }));
          }
        }
      }
    },
    [patchAssistant]
  );

  const onSend = async () => {
    const t = input.trim();
    if (!t || !sessionId || busy) return;
    setBusy(true);
    setInput("");
    setStatus("分析中（流式）…");
    try {
      await runStream(sessionId, t);
      setStatus("完成");
    } catch (e) {
      setStatus(`请求失败：${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app">
      <header>
        <div>
          <h1>智能数据分析师</h1>
          <p>上传 CSV / Excel，Agent 将生成 Pandas 代码、图表与 Markdown 结论</p>
        </div>
      </header>

      <div className="upload-row">
        <label className="btn" style={{ cursor: "pointer" }}>
          选择文件
          <input type="file" accept=".csv,.xlsx,.xls,.xlsm" hidden onChange={onUpload} />
        </label>
        <span className="thinking">{status}</span>
      </div>

      {previewText ? (
        <pre className="preview">
          <strong>数据预览</strong>
          {"\n"}
          {previewText}
        </pre>
      ) : null}

      <div className="chat">
        <div className="messages">
          {messages.map((m, i) => (
            <div key={i} className={`bubble ${m.role}`}>
              <div className="meta">{m.role === "user" ? "你" : "分析师"}</div>
              {m.role === "assistant" ? (
                <>
                  {m.content ? (
                    <div className="md">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                        {m.content}
                      </ReactMarkdown>
                    </div>
                  ) : busy && i === messages.length - 1 ? (
                    <div className="thinking">正在思考或执行代码…</div>
                  ) : null}
                  {(m.codeBlocks || []).map((c, j) => (
                    <div key={j}>
                      <div className="code-label">生成的代码 #{j + 1}</div>
                      <div className="code-wrap">
                        <SyntaxHighlighter
                          language="python"
                          style={oneDark}
                          PreTag="div"
                          customStyle={{ margin: 0 }}
                        >
                          {c}
                        </SyntaxHighlighter>
                      </div>
                    </div>
                  ))}
                  {(m.toolResults || []).length > 0 ? (
                    <details className="tool-result-details">
                      <summary>执行结果（点击展开）</summary>
                      {(m.toolResults || []).map((tr, j) => (
                        <pre key={j} className="tool-result">{tr}</pre>
                      ))}
                    </details>
                  ) : null}
                  {(m.images || []).length > 0 ? (
                    <div className="figure-row">
                      {(m.images || []).map((b64, j) => (
                        <img
                          key={j}
                          alt={`chart-${j}`}
                          src={`data:image/png;base64,${b64}`}
                          className="figure-thumb"
                          onClick={() => setLightboxSrc(`data:image/png;base64,${b64}`)}
                        />
                      ))}
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="md">{m.content}</div>
              )}
            </div>
          ))}
        </div>

        <div className="compose">
          <textarea
            placeholder={sessionId ? "描述你想做的分析…" : "请先上传数据文件"}
            value={input}
            disabled={!sessionId || busy}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void onSend();
              }
            }}
          />
          <button type="button" className="btn" disabled={!sessionId || busy} onClick={() => void onSend()}>
            发送
          </button>
        </div>
      </div>

      {lightboxSrc && (
        <div className="lightbox-overlay" onClick={() => setLightboxSrc(null)}>
          <div className="lightbox-content" onClick={(e) => e.stopPropagation()}>
            <img src={lightboxSrc} alt="放大查看" />
            <button className="lightbox-close" onClick={() => setLightboxSrc(null)}>✕</button>
          </div>
        </div>
      )}
    </div>
  );
}
