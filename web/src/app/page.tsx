"use client";

import { useEffect, useRef, useState, type MutableRefObject } from "react";

type SessionStatus = "idle" | "connecting" | "connected" | "stopping";

type VoiceEvent = {
  type: string;
  data?: Record<string, unknown>;
  provider?: string | null;
  provider_event?: string | null;
};

type EventRecord = VoiceEvent & {
  id: number;
  receivedAt: string;
};

type CreatedSession = {
  session_id: string;
  conversation_id: string;
  agent: string;
  mode: "chat" | "voice";
};

type ConversationMessage = {
  role?: string;
  content?: unknown;
};

const TARGET_SAMPLE_RATE = 16_000;
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Turn the configured HTTP API origin into the voice WebSocket endpoint. */
function createSocketUrl(agentName: string, conversationId: string): string {
  const url = new URL(API_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `${url.pathname.replace(/\/$/, "")}/v1/voice/${encodeURIComponent(agentName)}/${encodeURIComponent(conversationId)}`;
  return url.toString();
}

/** Convert signed PCM16 samples into the base64 payload expected by the API. */
function encodePcm16(samples: Float32Array): string {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);

  samples.forEach((sample, index) => {
    const clamped = Math.max(-1, Math.min(1, sample));
    view.setInt16(index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  });

  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return btoa(binary);
}

/** Resample microphone input to the 16 kHz stream required by Sarvam STT. */
function resample(samples: Float32Array, inputRate: number): Float32Array {
  if (inputRate === TARGET_SAMPLE_RATE) return samples;

  const ratio = inputRate / TARGET_SAMPLE_RATE;
  const outputLength = Math.round(samples.length / ratio);
  const output = new Float32Array(outputLength);

  for (let outputIndex = 0; outputIndex < outputLength; outputIndex += 1) {
    const start = Math.floor(outputIndex * ratio);
    const end = Math.min(Math.ceil((outputIndex + 1) * ratio), samples.length);
    let total = 0;
    for (let inputIndex = start; inputIndex < end; inputIndex += 1) total += samples[inputIndex];
    output[outputIndex] = total / Math.max(1, end - start);
  }

  return output;
}

/** Find human-readable text in the different payload shapes used by providers. */
function getText(data: Record<string, unknown> | undefined): string {
  if (!data) return "";
  const candidates = [data.text, data.transcript, data.content, data.message];
  const nested = data.data;
  if (nested && typeof nested === "object") {
    candidates.push((nested as Record<string, unknown>).text);
    candidates.push((nested as Record<string, unknown>).transcript);
  }
  return candidates.find((value): value is string => typeof value === "string") ?? "";
}

/** Render the string and block-shaped content returned by the agent history API. */
function getContentText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") return part;
        if (part && typeof part === "object") {
          const block = part as Record<string, unknown>;
          return typeof block.text === "string"
            ? block.text
            : typeof block.content === "string"
              ? block.content
              : "";
        }
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }
  if (content && typeof content === "object") {
    const value = content as Record<string, unknown>;
    return typeof value.text === "string"
      ? value.text
      : typeof value.content === "string"
        ? value.content
        : "";
  }
  return "";
}

/** Format the active call duration as a compact mm:ss clock. */
function formatCallDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
  const seconds = (totalSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

/** Read the complete persisted history for the active session. */
async function getConversationHistory(conversationId: string): Promise<ConversationMessage[]> {
  const response = await fetch(`${API_URL}/v1/conversations/${encodeURIComponent(conversationId)}`, {
    cache: "no-store",
  });
  if (response.status === 404) return [];
  const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(
      typeof payload.detail === "string" ? payload.detail : "Could not load conversation history.",
    );
  }
  return Array.isArray(payload.messages) ? (payload.messages as ConversationMessage[]) : [];
}

/** Ask Python to create the session ID used by this voice conversation. */
async function createVoiceSession(agentName: string): Promise<CreatedSession> {
  const response = await fetch(`${API_URL}/v1/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_name: agentName, mode: "voice" }),
  });
  const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(typeof payload.detail === "string" ? payload.detail : "Could not create a session.");
  }
  return payload as unknown as CreatedSession;
}

type AudioPlaybackPipeline = {
  audio: HTMLAudioElement;
  mediaSource: MediaSource;
  objectUrl: string;
  sourceBuffer: SourceBuffer | null;
  chunks: Uint8Array[];
  mimeType: string;
  generation: number;
  responseId: string | null;
  endWhenDrained: boolean;
  playbackCompletedNotified: boolean;
};

/** Use a MediaSource-compatible MIME type for Sarvam's audio metadata. */
function normalizeAudioMimeType(contentType: string | undefined): string {
  if (!contentType || contentType === "audio/mp3") return "audio/mpeg";
  return contentType;
}

/** Append all received chunks to one continuous browser playback pipeline. */
function appendAudioChunk(
  audio: string,
  contentType: string | undefined,
  pipelineRef: MutableRefObject<AudioPlaybackPipeline | null>,
  generationRef: MutableRefObject<number>,
  responseId: string | null,
  onPlaybackCompleted: (responseId: string | null) => void,
): void {
  const binary = atob(audio);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  const mimeType = normalizeAudioMimeType(contentType);
  let pipeline = pipelineRef.current;

  if (!pipeline || pipeline.generation !== generationRef.current) {
    if (typeof MediaSource === "undefined" || !MediaSource.isTypeSupported(mimeType)) {
      console.error(`Unsupported streaming audio format: ${mimeType}`);
      return;
    }

    const mediaSource = new MediaSource();
    const audioElement = new Audio();
    const objectUrl = URL.createObjectURL(mediaSource);
    pipeline = {
      audio: audioElement,
      mediaSource,
      objectUrl,
      sourceBuffer: null,
      chunks: [],
      mimeType,
      generation: generationRef.current,
      responseId,
      endWhenDrained: false,
      playbackCompletedNotified: false,
    };
    pipelineRef.current = pipeline;
    const activePipeline = pipeline;
    audioElement.src = objectUrl;
    audioElement.preload = "auto";
    audioElement.autoplay = true;

    mediaSource.addEventListener(
      "sourceopen",
      () => {
        if (activePipeline.generation !== generationRef.current) return;
        activePipeline.sourceBuffer = mediaSource.addSourceBuffer(mimeType);
        activePipeline.sourceBuffer.mode = "sequence";
        drainAudioPipeline(
          activePipeline,
          pipelineRef,
          generationRef,
          onPlaybackCompleted,
        );
        void audioElement.play().catch((error: unknown) => {
          console.warn("Unable to start streamed audio playback", error);
        });
      },
      { once: true },
    );
    audioElement.addEventListener("ended", () => {
      if (
        pipelineRef.current === activePipeline &&
        activePipeline.generation === generationRef.current &&
        !activePipeline.playbackCompletedNotified
      ) {
        activePipeline.playbackCompletedNotified = true;
        onPlaybackCompleted(activePipeline.responseId);
      }
    });
  }

  if (pipeline.mimeType !== mimeType) {
    console.warn(
      `Ignoring audio chunk with changing MIME type: ${mimeType}; expected ${pipeline.mimeType}`,
    );
    return;
  }

  pipeline.chunks.push(bytes);
  drainAudioPipeline(pipeline, pipelineRef, generationRef, onPlaybackCompleted);
}

/** Mark the current streamed response complete and let the audio element drain. */
function finishAudioPlayback(
  pipelineRef: MutableRefObject<AudioPlaybackPipeline | null>,
  generationRef: MutableRefObject<number>,
  onPlaybackCompleted: (responseId: string | null) => void,
  responseId: string | null,
): void {
  const pipeline = pipelineRef.current;
  if (!pipeline || pipeline.generation !== generationRef.current) {
    onPlaybackCompleted(responseId);
    return;
  }
  pipeline.endWhenDrained = true;
  drainAudioPipeline(pipeline, pipelineRef, generationRef, onPlaybackCompleted);
}

/** Append the next queued chunk once the SourceBuffer is ready. */
function drainAudioPipeline(
  pipeline: AudioPlaybackPipeline,
  pipelineRef: MutableRefObject<AudioPlaybackPipeline | null>,
  generationRef: MutableRefObject<number>,
  onPlaybackCompleted: (responseId: string | null) => void,
): void {
  const sourceBuffer = pipeline.sourceBuffer;
  if (
    pipelineRef.current !== pipeline ||
    pipeline.generation !== generationRef.current ||
    !sourceBuffer ||
    sourceBuffer.updating
  ) {
    return;
  }

  if (pipeline.chunks.length === 0) {
    if (
      pipeline.endWhenDrained &&
      pipeline.mediaSource.readyState === "open" &&
      !sourceBuffer.updating
    ) {
      pipeline.mediaSource.endOfStream();
    }
    return;
  }

  const chunk = pipeline.chunks.shift();
  if (!chunk) return;
  sourceBuffer.addEventListener(
    "updateend",
    () => drainAudioPipeline(pipeline, pipelineRef, generationRef, onPlaybackCompleted),
    { once: true },
  );
  sourceBuffer.appendBuffer(chunk as BufferSource);
}

/** Render the browser client for a live voice-agent session. */
export default function Home() {
  const [agentName, setAgentName] = useState("falcon");
  const [conversationId, setConversationId] = useState("");
  const [status, setStatus] = useState<SessionStatus>("idle");
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [liveUserMessage, setLiveUserMessage] = useState("");
  const [agentThinking, setAgentThinking] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [isTranscriptAtLatest, setIsTranscriptAtLatest] = useState(true);
  const [callStartedAt, setCallStartedAt] = useState<number | null>(null);
  const [callDurationSeconds, setCallDurationSeconds] = useState(0);
  const [partialTranscript, setPartialTranscript] = useState("");
  const [error, setError] = useState("");

  const socketRef = useRef<WebSocket | null>(null);
  const conversationIdRef = useRef("");
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const eventIdRef = useRef(0);
  const playbackGenerationRef = useRef(0);
  const playbackEnabledRef = useRef(false);
  const playbackPipelineRef = useRef<AudioPlaybackPipeline | null>(null);
  const playbackResponseIdRef = useRef<string | null>(null);
  const activeUserMessageRef = useRef("");
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const followTranscriptRef = useRef(true);

  /** Release microphone, audio-processing, and playback resources. */
  const cleanupMedia = () => {
    processorRef.current?.disconnect();
    sourceRef.current?.disconnect();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      void audioContextRef.current.close();
    }
    processorRef.current = null;
    sourceRef.current = null;
    streamRef.current = null;
    audioContextRef.current = null;
  };

  /** Stop any queued agent audio when a session is interrupted. */
  const stopPlayback = () => {
    playbackEnabledRef.current = false;
    playbackResponseIdRef.current = null;
    playbackGenerationRef.current += 1;
    const pipeline = playbackPipelineRef.current;
    if (!pipeline) return;
    if (pipeline.mediaSource.readyState === "open" && pipeline.sourceBuffer?.updating) {
      pipeline.sourceBuffer.abort();
    }
    pipeline.audio.pause();
    pipeline.audio.removeAttribute("src");
    pipeline.audio.load();
    URL.revokeObjectURL(pipeline.objectUrl);
    playbackPipelineRef.current = null;
  };

  /** Tell the server after the current agent response finishes playing. */
  const notifyPlaybackCompleted = (responseId: string | null) => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN && responseId) {
      socket.send(JSON.stringify({ type: "playback.completed", response_id: responseId }));
    }
  };

  /** Start a microphone pipeline that emits small PCM16 WebSocket frames. */
  const startMicrophone = async (socket: WebSocket, providedStream?: MediaStream) => {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser does not provide microphone access.");
    }

    const stream = providedStream ?? (await navigator.mediaDevices.getUserMedia({ audio: true }));
    const audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    const silentOutput = audioContext.createGain();
    silentOutput.gain.value = 0;

    processor.onaudioprocess = (audioEvent) => {
      if (socket.readyState !== WebSocket.OPEN) return;
      const input = audioEvent.inputBuffer.getChannelData(0);
      const pcm = resample(input, audioContext.sampleRate);
      socket.send(JSON.stringify({ type: "audio", audio: encodePcm16(pcm) }));
    };

    streamRef.current = stream;
    audioContextRef.current = audioContext;
    sourceRef.current = source;
    processorRef.current = processor;
    source.connect(processor);
    processor.connect(silentOutput);
    silentOutput.connect(audioContext.destination);
  };

  /** Replace the local timeline with the server's complete persisted history. */
  const refreshConversationHistory = async (id: string) => {
    if (!id) return;
    setHistoryLoading(true);
    try {
      const history = await getConversationHistory(id);
      if (conversationIdRef.current === id) setMessages(history);
    } catch (historyError) {
      if (conversationIdRef.current === id) {
        setError(
          historyError instanceof Error
            ? historyError.message
            : "Could not load conversation history.",
        );
      }
    } finally {
      if (conversationIdRef.current === id) setHistoryLoading(false);
    }
  };

  /** Keep the live transcript at the newest turn unless the user scrolls up. */
  const scrollTranscriptToLatest = (behavior: ScrollBehavior = "smooth") => {
    const transcript = transcriptRef.current;
    if (!transcript) return;
    transcript.scrollTo({ top: transcript.scrollHeight, behavior });
    followTranscriptRef.current = true;
  };

  useEffect(() => {
    if (!followTranscriptRef.current) return;
    const frame = requestAnimationFrame(() => scrollTranscriptToLatest("smooth"));
    return () => cancelAnimationFrame(frame);
  }, [messages, liveUserMessage, partialTranscript, agentThinking]);

  useEffect(() => {
    if (callStartedAt === null || status === "idle") return;
    const updateDuration = () => {
      setCallDurationSeconds(Math.floor((Date.now() - callStartedAt) / 1000));
    };
    updateDuration();
    const timer = window.setInterval(updateDuration, 1000);
    return () => window.clearInterval(timer);
  }, [callStartedAt, status]);

  /** Handle one normalized event from the Python voice session. */
  const handleVoiceEvent = (voiceEvent: VoiceEvent) => {
    const record: EventRecord = {
      ...voiceEvent,
      id: eventIdRef.current++,
      receivedAt: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };
    setEvents((current) => [...current, record]);

    const text = getText(voiceEvent.data);
    if (voiceEvent.type === "transcript.partial") setPartialTranscript(text);
    if (voiceEvent.type === "transcript.final") {
      activeUserMessageRef.current = text;
      setLiveUserMessage(text);
      setPartialTranscript("");
      setAgentThinking(true);
    }
    if (voiceEvent.type === "speech.started") {
      // Barge-in must silence the current reply immediately. Ignore stale
      // provider audio until the next agent response explicitly starts.
      stopPlayback();
      if (activeUserMessageRef.current) {
        const interruptedMessage = activeUserMessageRef.current;
        setMessages((current) => [...current, { role: "user", content: interruptedMessage }]);
        activeUserMessageRef.current = "";
        setLiveUserMessage("");
        setAgentThinking(false);
      }
    }
    if (voiceEvent.type === "agent.started") {
      // Each response gets a fresh MediaSource and playback acknowledgement.
      stopPlayback();
      playbackEnabledRef.current = true;
      playbackResponseIdRef.current =
        typeof voiceEvent.data?.response_id === "string"
          ? voiceEvent.data.response_id
          : null;
      setAgentThinking(true);
    }
    if (voiceEvent.type === "agent.completed") {
      const completedUserMessage = activeUserMessageRef.current;
      if (completedUserMessage || text) {
        setMessages((current) => [
          ...current,
          ...(completedUserMessage
            ? [{ role: "user", content: completedUserMessage }]
            : []),
          ...(text ? [{ role: "assistant", content: text }] : []),
        ]);
      }
      activeUserMessageRef.current = "";
      setLiveUserMessage("");
      setAgentThinking(false);
      void refreshConversationHistory(conversationIdRef.current);
    }
    if (voiceEvent.type === "error") setError(text || "The voice session returned an error.");
    if (voiceEvent.type === "synthesis.completed") {
      finishAudioPlayback(
        playbackPipelineRef,
        playbackGenerationRef,
        notifyPlaybackCompleted,
        playbackResponseIdRef.current,
      );
    }

    if (voiceEvent.type === "audio.output") {
      const data = voiceEvent.data ?? {};
      if (playbackEnabledRef.current && typeof data.audio === "string") {
        appendAudioChunk(
          data.audio,
          typeof data.content_type === "string" ? data.content_type : undefined,
          playbackPipelineRef,
          playbackGenerationRef,
          playbackResponseIdRef.current,
          notifyPlaybackCompleted,
        );
      }
    }
  };

  /** Close the active socket and reset browser media resources. */
  const stopSession = () => {
    setStatus("stopping");
    if (callStartedAt !== null) {
      setCallDurationSeconds(Math.floor((Date.now() - callStartedAt) / 1000));
    }
    const socket = socketRef.current;
    if (activeUserMessageRef.current) {
      const unfinishedMessage = activeUserMessageRef.current;
      setMessages((current) => [...current, { role: "user", content: unfinishedMessage }]);
      activeUserMessageRef.current = "";
      setLiveUserMessage("");
    }
    setAgentThinking(false);
    cleanupMedia();
    stopPlayback();
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "stop" }));
      socket.close(1000, "Client stopped session");
    }
    socketRef.current = null;
    setStatus("idle");
  };

  /** Open the backend voice route and attach microphone/event handlers. */
  const startSession = async () => {
    if (status !== "idle") return;
    if (!agentName.trim()) {
      setError("Enter an agent name first.");
      return;
    }

    setError("");
    setEvents([]);
    setMessages([]);
    followTranscriptRef.current = true;
    setIsTranscriptAtLatest(true);
    setHistoryLoading(false);
    conversationIdRef.current = "";
    setCallStartedAt(null);
    setCallDurationSeconds(0);
    activeUserMessageRef.current = "";
    setLiveUserMessage("");
    setAgentThinking(false);
    setPartialTranscript("");
    setStatus("connecting");

    try {
      // Session IDs are generated by Python and reused as conversation IDs.
      const session = await createVoiceSession(agentName.trim());
      setConversationId(session.session_id);
      conversationIdRef.current = session.session_id;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const socket = new WebSocket(createSocketUrl(agentName.trim(), session.session_id));
      socketRef.current = socket;

      socket.onopen = async () => {
        try {
          await startMicrophone(socket, stream);
          setCallStartedAt(Date.now());
          setStatus("connected");
        } catch (mediaError) {
          setError(mediaError instanceof Error ? mediaError.message : "Microphone setup failed.");
          socket.close();
        }
      };
      socket.onmessage = (message) => {
        try {
          handleVoiceEvent(JSON.parse(message.data) as VoiceEvent);
        } catch {
          setError("Received an invalid event from the voice server.");
        }
      };
      socket.onerror = () => setError("Could not connect to the voice server.");
      socket.onclose = () => {
        cleanupMedia();
        stopPlayback();
        socketRef.current = null;
        setStatus("idle");
      };
    } catch (connectionError) {
      cleanupMedia();
      setStatus("idle");
      setError(connectionError instanceof Error ? connectionError.message : "Could not start session.");
    }
  };

  useEffect(() => {
    return () => {
      processorRef.current?.disconnect();
      sourceRef.current?.disconnect();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      void audioContextRef.current?.close();
      playbackEnabledRef.current = false;
      const pipeline = playbackPipelineRef.current;
      if (pipeline) {
        playbackGenerationRef.current += 1;
        if (pipeline.mediaSource.readyState === "open" && pipeline.sourceBuffer?.updating) {
          pipeline.sourceBuffer.abort();
        }
        pipeline.audio.pause();
        pipeline.audio.removeAttribute("src");
        pipeline.audio.load();
        URL.revokeObjectURL(pipeline.objectUrl);
        playbackPipelineRef.current = null;
      }
      socketRef.current?.close();
    };
  }, []);

  const isActive = status !== "idle";
  const statusLabel = { idle: "Ready", connecting: "Connecting", connected: "Live", stopping: "Ending" }[status];

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand-mark"><span className="brand-dot" /> voice<span>.ai</span></div>
        <div className="topbar-meta"><span className="service-status"><i /> system ready</span><span className="topbar-note"><span className="signal-bars" /> realtime voice workspace</span></div>
      </header>

      <section className="hero">
        <div className="eyebrow"><span /> voice agent console <b>01 / LIVE</b></div>
        <div className="hero-content">
          <div>
            <h1>Talk to your <em>agent.</em></h1>
            <p>Open a live voice channel, speak naturally, and watch every turn move through the agent in real time.</p>
          </div>
          <div className="hero-note"><span className="hero-note-icon">↗</span><span><strong>Full history</strong><br />Every turn stays in the room.</span></div>
        </div>
      </section>

      <section className="workspace">
        <aside className="control-card card">
          <div className="card-heading"><div><span className="section-kicker">SESSION</span><h2>Connection</h2></div><span className={`status-pill ${status}`}><i /> {statusLabel}</span></div>
          <div className="connection-intro"><span className="connection-icon">◉</span><span>Microphone channel<br /><strong>{isActive ? "Listening for your voice" : "Ready when you are"}</strong></span></div>
          <div className="field-group"><label htmlFor="agent">Agent</label><input id="agent" value={agentName} onChange={(event) => setAgentName(event.target.value)} disabled={isActive} /><small>Dynamic agent package name</small></div>
          <div className="field-group"><label htmlFor="conversation">Session ID</label><input id="conversation" value={conversationId} placeholder="Created when session starts" readOnly /><small>Generated by Python · used as conversation ID</small></div>
          <button className={`session-button ${isActive ? "stop" : "start"}`} onClick={isActive ? stopSession : startSession}><span className="button-icon">{isActive ? "■" : "●"}</span>{isActive ? "End session" : "Start speaking"}<span className="button-arrow">↗</span></button>
          <p className="mic-hint">Your browser will ask for microphone permission when the session starts.</p>
          <div className="connection-detail"><div><span>Endpoint</span><code>{API_URL.replace(/^https?:\/\//, "")}</code></div><div><span>Format</span><strong>PCM16 · 16 kHz</strong></div><div><span>Retention</span><strong>Complete history</strong></div></div>
        </aside>

        <div className="conversation-card card">
          <div className="card-heading conversation-heading"><div><span className="section-kicker">LIVE TRANSCRIPT</span><h2>Conversation</h2></div><div className="conversation-meta"><span className="history-count">{messages.length + (liveUserMessage ? 1 : 0)} messages</span><span className={`call-time ${status}`}><i /> {formatCallDuration(callDurationSeconds)}</span></div></div>
          <div className="transcript-toolbar"><span><i className="live-dot" /> {historyLoading ? "Syncing history" : "History retained for this session"}</span><span>{agentName.toUpperCase()} / VOICE</span></div>
          <div
            className="transcript-window"
            ref={transcriptRef}
            onScroll={(event) => {
              const transcript = event.currentTarget;
              const distanceFromLatest = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight;
              followTranscriptRef.current = distanceFromLatest < 48;
              setIsTranscriptAtLatest(followTranscriptRef.current);
            }}
          >
            {!messages.length && !liveUserMessage && !partialTranscript ? <div className="empty-state"><div className="empty-icon">◌</div><strong>Your conversation will appear here</strong><span>Start a session, then speak into your microphone.</span></div> : <div className="message-list">
              {messages.map((message, index) => {
                const isUser = message.role === "user";
                return <div className={`message ${isUser ? "user-message" : "agent-message"}`} key={`${message.role ?? "message"}-${index}`}><span className="message-label">{isUser ? "YOU" : agentName.toUpperCase()}</span><p>{getContentText(message.content)}</p></div>;
              })}
              {liveUserMessage && <div className="message user-message live-message"><span className="message-label">YOU · JUST NOW</span><p>{liveUserMessage}</p></div>}
              {partialTranscript && <div className="message partial-message"><span className="message-label">LISTENING</span><p>{partialTranscript}<span className="typing-caret" /></p></div>}
              {agentThinking && !partialTranscript && <div className="message agent-message thinking-message"><span className="message-label">{agentName.toUpperCase()} · THINKING</span><p><span className="thinking-dots"><i /><i /><i /></span></p></div>}
            </div>}
            {!isTranscriptAtLatest && <button className="jump-latest" onClick={() => { scrollTranscriptToLatest(); setIsTranscriptAtLatest(true); }}>↓ Latest message</button>}
          </div>
          <div className="event-stream"><div className="stream-header"><span>EVENT STREAM</span><span className="live-dot" /><span>complete session log</span></div><div className="event-list">{events.map((event) => <div className="event-row" key={event.id}><time>{event.receivedAt}</time><strong>{event.type}</strong><span>{event.provider_event || event.provider || "app"}</span></div>)}{!events.length && <div className="event-placeholder">Waiting for socket events…</div>}</div></div>
        </div>
      </section>

      {error && <div className="error-banner"><strong>Connection issue</strong><span>{error}</span><button onClick={() => setError("")} aria-label="Dismiss error">×</button></div>}
      <footer><span>VOICE AI</span><span>Powered by your FastAPI agent runtime</span></footer>
    </main>
  );
}
