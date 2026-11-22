import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useAuth } from '../context/AuthContext';
import {
  fetchChatSessionsApi,
  createChatSessionApi,
  deleteChatSessionApi,
  fetchMessagesApi,
  sendMessageApi,
  uploadDocumentApi,
} from '../api';
import {
  Plus,
  Trash2,
  Paperclip,
  ArrowRight,
  UploadCloud,
  FileText,
  Loader2,
} from 'lucide-react';

export default function AskPage({ onNavigateKnowledgeBase }) {
  const { user, activeSessionId, setActiveSessionId, sessionUploadedDocs, addSessionDoc } = useAuth();

  const [sessions, setSessions] = useState([]);
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [hoveredSessionId, setHoveredSessionId] = useState(null);
  const isCreatingSessionForSendRef = useRef(false);

  const fileInputRef = useRef(null);
  const messagesEndRef = useRef(null);

  // Load chat sessions on mount
  useEffect(() => {
    loadSessions();
  }, []);

  // When active session changes, load messages
  useEffect(() => {
    if (activeSessionId) {
      if (isCreatingSessionForSendRef.current) {
        // Skip reloading empty messages when session was just auto-created for sending
        isCreatingSessionForSendRef.current = false;
        return;
      }
      loadMessages(activeSessionId);
    } else {
      setMessages([]);
    }
  }, [activeSessionId]);

  // Scroll to bottom when messages update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending]);

  const loadSessions = async () => {
    try {
      const data = await fetchChatSessionsApi();
      const sessList = data.sessions || [];
      setSessions(sessList);
      if (sessList.length > 0 && !activeSessionId) {
        setActiveSessionId(sessList[0].id);
      }
    } catch (err) {
      console.error('Failed to load sessions:', err);
    }
  };

  const loadMessages = async (sessId) => {
    try {
      const data = await fetchMessagesApi(sessId);
      setMessages(data.messages || []);
    } catch (err) {
      console.error('Failed to load messages:', err);
    }
  };

  const handleNewChat = async () => {
    try {
      const data = await createChatSessionApi('New Chat');
      if (data?.session) {
        setSessions([data.session, ...sessions]);
        setActiveSessionId(data.session.id);
        setMessages([]);
      }
    } catch (err) {
      console.error('Failed to create new chat:', err);
    }
  };

  const handleDeleteSession = async (sessId, e) => {
    e.stopPropagation();
    try {
      // Immediate deletion without confirmation as required
      await deleteChatSessionApi(sessId);
      const remaining = sessions.filter((s) => s.id !== sessId);
      setSessions(remaining);
      if (activeSessionId === sessId) {
        setActiveSessionId(remaining.length > 0 ? remaining[0].id : null);
      }
    } catch (err) {
      console.error('Failed to delete chat:', err);
    }
  };

  const handleSendMessage = async (e) => {
    e?.preventDefault();
    if (!inputMessage.trim() || sending) return;

    let currentSessId = activeSessionId;
    if (!currentSessId) {
      // Create new session if none active
      isCreatingSessionForSendRef.current = true;
      const sessRes = await createChatSessionApi('New Chat');
      currentSessId = sessRes.session.id;
      setSessions([sessRes.session, ...sessions]);
      setActiveSessionId(currentSessId);
    }

    const userText = inputMessage.trim();
    setInputMessage('');
    const tempUserMsg = {
      id: Date.now().toString(),
      role: 'user',
      content: userText,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);
    setSending(true);

    try {
      const res = await sendMessageApi(currentSessId, userText);
      if (res?.assistant_message) {
        setMessages((prev) => [...prev, res.assistant_message]);
        // Refresh session list to update title and order
        loadSessions();
      }
    } catch (err) {
      console.error('Send error:', err);
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: 'Sorry, an error occurred while processing your query. Please try again.',
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    try {
      const res = await uploadDocumentApi(file, activeSessionId || '');
      if (res?.document) {
        // Add to active session document list
        addSessionDoc(res.document);
      }
    } catch (err) {
      alert('Document upload failed. Please try again.');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return (
    <div className="flex h-[calc(100vh-64px)] w-full overflow-hidden bg-white">
      {/* Hidden File Input */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileUpload}
        className="hidden"
        accept=".pdf,.jpg,.jpeg,.png,.docx,.xlsx"
      />

      {/* Left Sidebar */}
      <aside className="w-64 border-r border-gray-100 flex flex-col justify-between p-4 bg-white flex-shrink-0">
        <div className="space-y-6 overflow-y-auto">
          {/* New Chat Button */}
          <button
            onClick={handleNewChat}
            className="w-full bg-[#18181B] hover:bg-black text-white text-xs font-semibold py-2.5 px-4 rounded-xl flex items-center justify-center space-x-2 transition-all shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New Chat</span>
          </button>

          {/* Recent Chats Section */}
          <div>
            <p className="text-[10px] font-bold text-gray-400 tracking-wider uppercase mb-2 px-1">
              Recent Chats
            </p>
            <div className="space-y-1">
              {sessions.length === 0 ? (
                <p className="text-xs text-gray-400 px-1 py-1 italic">No recent chats</p>
              ) : (
                sessions.map((sess) => {
                  const isActive = sess.id === activeSessionId;
                  const isHovered = sess.id === hoveredSessionId;

                  return (
                    <div
                      key={sess.id}
                      onClick={() => setActiveSessionId(sess.id)}
                      onMouseEnter={() => setHoveredSessionId(sess.id)}
                      onMouseLeave={() => setHoveredSessionId(null)}
                      className={`group flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer text-xs font-medium transition-all ${
                        isActive
                          ? 'bg-gray-100/80 text-gray-900 font-semibold'
                          : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                      }`}
                    >
                      <span className="truncate pr-2">{sess.title || 'New Chat'}</span>

                      {/* Dustbin icon on hover: immediately deletes chat without confirmation */}
                      {isHovered && (
                        <button
                          onClick={(e) => handleDeleteSession(sess.id, e)}
                          title="Delete chat"
                          className="text-gray-400 hover:text-red-500 transition-colors p-0.5"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Knowledge Base (Session Uploads) Section */}
          <div className="pt-2 border-t border-gray-100">
            <div className="flex items-center justify-between mb-2.5 px-1">
              <span className="text-[10px] font-bold text-gray-400 tracking-wider uppercase">
                Knowledge Base
              </span>
              <button
                onClick={onNavigateKnowledgeBase}
                className="text-[11px] font-medium text-gray-500 hover:text-gray-900 transition-colors"
              >
                View All
              </button>
            </div>

            {/* Upload Box */}
            <div
              onClick={() => fileInputRef.current?.click()}
              className="border border-dashed border-gray-200 hover:border-gray-400 rounded-xl p-3 text-center cursor-pointer transition-all bg-gray-50/50 hover:bg-gray-50 mb-3"
            >
              <div className="flex flex-col items-center space-y-1">
                {uploading ? (
                  <Loader2 className="w-4 h-4 text-gray-500 animate-spin" />
                ) : (
                  <UploadCloud className="w-4 h-4 text-gray-500" />
                )}
                <span className="text-[11px] font-medium text-gray-700">
                  {uploading ? 'Processing report...' : 'Upload medical reports (PDF, JPG)'}
                </span>
              </div>
            </div>

            {/* Temporary Session Documents List */}
            <div className="space-y-2">
              {sessionUploadedDocs.length === 0 ? (
                <p className="text-[11px] text-gray-400 px-1 py-1 italic leading-tight">
                  No reports uploaded in current session.
                </p>
              ) : (
                sessionUploadedDocs.map((doc, idx) => (
                  <div
                    key={doc.id || idx}
                    className="flex items-start space-x-2.5 p-2 rounded-lg bg-gray-50/70 border border-gray-100"
                  >
                    <FileText className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-gray-800 truncate">
                        {doc.file_name}
                      </p>
                      <p className="text-[10px] text-gray-400">
                        {doc.file_size} •{' '}
                        <span
                          className={
                            doc.status === 'indexed'
                              ? 'text-emerald-600 font-medium'
                              : 'text-amber-500 font-medium'
                          }
                        >
                          {doc.status === 'indexed' ? 'Indexed' : 'Processing'}
                        </span>
                      </p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* User Info Footer in Sidebar */}
        <div className="pt-4 border-t border-gray-100 flex items-center space-x-2.5 px-1">
          {user?.picture ? (
            <img src={user.picture} alt={user.name} className="w-7 h-7 rounded-full object-cover" />
          ) : (
            <div className="w-7 h-7 rounded-full bg-gray-200 text-gray-700 flex items-center justify-center text-xs font-bold">
              {user?.name?.[0] || 'U'}
            </div>
          )}
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-gray-900 truncate">{user?.name}</p>
            <p className="text-[10px] text-gray-400 truncate">{user?.email}</p>
          </div>
        </div>
      </aside>

      {/* Main Chat Area */}
      <main className="flex-1 flex flex-col justify-between h-full overflow-hidden bg-white">
        {/* Chat Messages Container */}
        <div className="flex-1 overflow-y-auto px-8 py-8 space-y-6 max-w-4xl w-full mx-auto">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center py-20 text-gray-400 space-y-3">
              <span className="text-3xl font-bold tracking-tight text-gray-900">
                MI<sup className="text-base font-semibold ml-0.5">2</sup>A
              </span>
              <p className="text-sm font-medium text-gray-600 max-w-md">
                Ask any question about clinical guidelines, medical symptoms, diagnoses, or upload reports for evidence-grounded analysis.
              </p>
            </div>
          ) : (
            messages.map((msg, idx) => {
              const isUser = msg.role === 'user';
              return (
                <div key={msg.id || idx} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                  {isUser ? (
                    // User Message Bubble (Right)
                    <div className="max-w-xl bg-[#F3F4F6] text-gray-900 px-5 py-3 rounded-2xl text-sm leading-relaxed">
                      {msg.content}
                    </div>
                  ) : (
                    // Assistant Message Card (Left)
                    <div className="max-w-2xl bg-white border border-gray-100 rounded-2xl p-6 shadow-sm space-y-4">
                      <div className="text-sm text-gray-800 leading-relaxed markdown-content">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            p: ({ children }) => <p className="mb-3 leading-relaxed last:mb-0">{children}</p>,
                            strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
                            ul: ({ children }) => <ul className="list-disc pl-5 mb-3 space-y-1.5">{children}</ul>,
                            ol: ({ children }) => <ol className="list-decimal pl-5 mb-3 space-y-1.5">{children}</ol>,
                            li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                            h1: ({ children }) => <h1 className="text-base font-bold text-gray-900 mb-2 mt-4 first:mt-0">{children}</h1>,
                            h2: ({ children }) => <h2 className="text-sm font-bold text-gray-900 mb-2 mt-3 first:mt-0">{children}</h2>,
                            h3: ({ children }) => <h3 className="text-sm font-semibold text-gray-900 mb-1.5 mt-2 first:mt-0">{children}</h3>,
                            code: ({ inline, children }) =>
                              inline ? (
                                <code className="bg-gray-100 px-1 py-0.5 rounded text-xs font-mono text-gray-800">{children}</code>
                              ) : (
                                <pre className="bg-gray-50 p-3 rounded-lg text-xs font-mono overflow-x-auto my-2 border border-gray-100">{children}</pre>
                              ),
                          }}
                        >
                          {msg.content}
                        </ReactMarkdown>
                      </div>

                      {/* Source Context Box */}
                      {msg.source_context && (
                        <div className="bg-gray-50/80 border border-gray-100 rounded-xl p-3.5 space-y-1">
                          <p className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">
                            Source Context:
                          </p>
                          <p className="text-xs text-gray-600 font-mono italic leading-relaxed">
                            {msg.source_context}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}

          {sending && (
            <div className="flex justify-start">
              <div className="bg-white border border-gray-100 rounded-2xl p-4 shadow-sm flex items-center space-x-2 text-xs text-gray-500">
                <Loader2 className="w-4 h-4 animate-spin text-gray-600" />
                <span>Searching knowledge base and formulating response...</span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar & Footer */}
        <div className="p-6 bg-white max-w-4xl w-full mx-auto">
          <form
            onSubmit={handleSendMessage}
            className="flex items-center bg-[#F3F4F6] rounded-full px-5 py-3 shadow-sm border border-gray-200/80 focus-within:border-gray-400 transition-all"
          >
            {/* Paperclip attachment icon */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="text-gray-400 hover:text-gray-700 transition-colors mr-3 focus:outline-none"
              title="Attach medical document"
            >
              <Paperclip className="w-4 h-4" />
            </button>

            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              placeholder="Ask..."
              className="w-full bg-transparent text-sm text-gray-900 placeholder-gray-400 focus:outline-none"
            />

            {/* Send Arrow Button */}
            <button
              type="submit"
              disabled={!inputMessage.trim() || sending}
              className={`ml-3 p-1.5 rounded-full transition-all ${
                inputMessage.trim() && !sending
                  ? 'bg-gray-900 text-white hover:bg-black'
                  : 'text-gray-300 cursor-not-allowed'
              }`}
            >
              <ArrowRight className="w-4 h-4" />
            </button>
          </form>

          {/* Sub-footer Attribution */}
          <p className="text-[11px] text-gray-400 text-center mt-3 tracking-tight">
            Powered by Groq AI. Verify medical information with qualified healthcare professional.
          </p>
        </div>
      </main>
    </div>
  );
}

