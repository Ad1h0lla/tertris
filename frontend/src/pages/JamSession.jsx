import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useProjectStore } from '../store/projectStore';
import { api, ApiError } from '../api/client';
import { Send, ArrowRight } from 'lucide-react';

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Formats an ApiError (or any Error) into a developer-readable string for
 * display in the chat when a backend call fails. Never hides the real error.
 */
function formatApiError(err) {
  if (err instanceof ApiError) {
    let msg = `❌ Backend error on ${err.endpoint}\n`;
    msg += `   HTTP ${err.status} ${err.statusText}\n`;
    if (err.detail) msg += `   Detail: ${err.detail}\n`;
    if (err.body && typeof err.body === 'object') {
      const bodyStr = JSON.stringify(err.body, null, 2);
      if (bodyStr.length < 600) msg += `   Response: ${bodyStr}`;
    }
    return msg.trim();
  }
  return `❌ Request failed: ${err.message || String(err)}`;
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function JamSession() {
  const { id } = useParams();
  const navigate = useNavigate();

  const {
    jamSession,
    understanding,
    addJamMessage,
    startJamSession,
    setUnderstanding,
  } = useProjectStore();

  const [inputText, setInputText]   = useState('');
  const [isThinking, setIsThinking] = useState(false);
  const [showFinish, setShowFinish] = useState(false);
  const chatEndRef                  = useRef(null);

  // Track the message count across renders without causing re-renders
  const userMsgCountRef = useRef(0);

  // ── Init ────────────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!jamSession.isActive && jamSession.messages.length === 0) {
      startJamSession(
        "What do you want to build? Describe it however feels natural — I'll figure out the rest."
      );
    }
  }, []); // run once on mount

  // ── Auto-scroll ─────────────────────────────────────────────────────────────

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [jamSession.messages, isThinking]);

  // ── Send ────────────────────────────────────────────────────────────────────

  const handleSend = useCallback(async () => {
    const text = inputText.trim();
    if (!text || isThinking) return;

    setInputText('');

    // 1. Add user message to store FIRST (so it's visible immediately)
    const userMsg = { role: 'user', content: text, ts: Date.now() };
    addJamMessage(userMsg);
    userMsgCountRef.current += 1;
    const isFirstMessage = userMsgCountRef.current === 1;

    setIsThinking(true);

    try {
      // 2. Build the correct history payload.
      //    - `idea`  = the message the user just typed (latest input)
      //    - `conversation_history` = all PREVIOUS messages (everything in the
      //      store BEFORE this one, i.e. jamSession.messages before we added this)
      //    We read jamSession.messages from the store at call time; because we
      //    already addJamMessage'd above, we exclude the last entry (this message).
      const currentMessages = useProjectStore.getState().jamSession.messages;
      const previousMessages = currentMessages
        .slice(0, -1) // exclude the message we just added
        .map(m => ({ role: m.role, content: m.content }));

      let res;

      if (isFirstMessage) {
        // ── First message: call /intake to get structured goal ────────────────
        res = await api.intake(text, previousMessages);

        // Map the flat backend response correctly.
        // Backend returns: { understood_goal, confidence, recommended_phases,
        //                    phase_names, recommended_agents, idea_type, ... }
        // NOT { goal: { ... } }
        if (res && res.understood_goal) {
          setUnderstanding(res); // store the full flat object
        }

        // Derive the agent reply.
        // New backend route returns `reply` at the top level (from generate_smart_reply).
        // Fall back to clarifying_questions or a simple confirmation.
        const questions = res?.clarifying_questions || [];
        const agentReply = res?.reply
          || (questions.length > 0 ? questions[0] : null)
          || (res?.understood_goal
            ? `Got it. I understand you want to: ${res.understood_goal}. What else should I know?`
            : 'Tell me more — what problem does this solve?');

        addJamMessage({ role: 'agent', content: agentReply, ts: Date.now() });

        // Show finish button when backend signals ready, or when confidence ≥ 0.8
        if (res?.ready === true || (res?.confidence ?? 0) >= 0.8) {
          setShowFinish(true);
        }

      } else {
        // ── Subsequent messages: call /intake/reply for smart reply ───────────
        const currentGoal = useProjectStore.getState().understanding || {};

        res = await api.intakeReply(text, previousMessages, currentGoal);

        // /intake/reply returns: { reply: string, ready: bool }
        const agentReply = res?.reply || 'Can you tell me more?';
        addJamMessage({ role: 'agent', content: agentReply, ts: Date.now() });

        // Backend signals readiness via the `ready` field
        if (res?.ready === true) {
          setShowFinish(true);
        }

        // Also re-run intake in background to keep understanding fresh
        // (only if the user has sent 3+ messages — avoid excessive LLM calls)
        if (userMsgCountRef.current >= 3) {
          try {
            const freshGoal = await api.intake(
              text,
              previousMessages,
            );
            if (freshGoal?.understood_goal) {
              setUnderstanding(freshGoal);
            }
          } catch {
            // Background refresh failure is non-fatal — don't surface it
          }
        }
      }

    } catch (err) {
      // Show the REAL error — never substitute a generic "Connection error."
      const errorText = formatApiError(err);
      addJamMessage({ role: 'agent', content: errorText, ts: Date.now() });
    } finally {
      setIsThinking(false);
    }
  }, [inputText, isThinking, addJamMessage, setUnderstanding]);

  // ── Finish ──────────────────────────────────────────────────────────────────

  const handleFinish = () => {
    navigate(`/project/${id}/understanding`);
  };

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="jam-session">
      <div className="jam-header">
        <div>
          <div className="jam-title">JAM SESSION</div>
          <div className="jam-subtitle">Interactive Idea Extraction</div>
        </div>
        {showFinish && (
          <button className="new-project-btn" onClick={handleFinish}>
            Generate Understanding <ArrowRight size={14} />
          </button>
        )}
      </div>

      <div className="jam-chat-body">
        {jamSession.messages.map((m, i) => (
          <div key={i} className="msg-row">
            <div className={`msg-prefix ${m.role}`}>
              {m.role === 'user' ? 'USR >' : 'SYS >'}
            </div>
            <div className="msg-container">
              <div className={`msg-content ${m.role === 'agent' ? 'agent-msg' : ''}`}
                   style={{ whiteSpace: 'pre-wrap' }}>
                {m.content}
              </div>
            </div>
          </div>
        ))}

        {isThinking && (
          <div className="msg-row">
            <div className="msg-prefix agent">SYS &gt;</div>
            <div className="msg-container">
              <div className="msg-content agent-msg">...</div>
            </div>
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      <div className="jam-input-container">
        <div className="input-prompt">INPUT<span className="cursor">_</span></div>
        <div className="input-row">
          <textarea
            className="term-input"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Type your idea..."
            rows={2}
            disabled={isThinking}
          />
          <button
            className="send-btn"
            onClick={handleSend}
            disabled={isThinking || !inputText.trim()}
          >
            <Send size={16} />
          </button>
        </div>
        <div className="input-hint">Press Enter to send, Shift+Enter for new line.</div>
      </div>
    </div>
  );
}
