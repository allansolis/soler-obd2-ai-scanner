import { useState, useRef, useEffect } from 'react'
import { Send, Bot, User, Sparkles, Car, Wrench, Gauge } from 'lucide-react'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  vehicleDataAccess?: string
}

const INITIAL_MESSAGES: Message[] = [
  {
    id: '1',
    role: 'assistant',
    content:
      'Hello! I\'m your SOLER AI diagnostic assistant. I have access to your vehicle\'s real-time sensor data, DTCs, and full repair database. How can I help you today?',
    timestamp: new Date(),
  },
]

const QUICK_SUGGESTIONS = [
  { icon: Car, text: 'Why is my check engine light on?' },
  { icon: Wrench, text: 'Explain my DTC codes' },
  { icon: Gauge, text: 'Is my engine running healthy?' },
  { icon: Sparkles, text: 'Suggest maintenance schedule' },
]

const MOCK_RESPONSES: Record<string, { content: string; vehicleDataAccess?: string }> = {
  default: {
    content:
      'I\'ve analyzed your vehicle data. Based on the current sensor readings, your engine appears to be running within normal parameters. The coolant temperature is stable, and fuel trims are within the expected range. Would you like me to run a more detailed analysis on any specific system?',
    vehicleDataAccess: 'Accessed: RPM, Coolant Temp, Fuel Trims, O2 Sensor',
  },
}

export default function AIChat() {
  const [messages, setMessages] = useState<Message[]>(INITIAL_MESSAGES)
  const [input, setInput] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const handleSend = () => {
    if (!input.trim()) return
    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setIsTyping(true)

    setTimeout(() => {
      const resp = MOCK_RESPONSES.default
      const aiMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: resp.content,
        timestamp: new Date(),
        vehicleDataAccess: resp.vehicleDataAccess,
      }
      setMessages(prev => [...prev, aiMsg])
      setIsTyping(false)
    }, 1500)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-6 pb-0">
        <h1 className="text-2xl font-bold text-white">AI Assistant</h1>
        <p className="text-sm text-slate-500">Powered by vehicle-aware AI diagnostics</p>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-auto p-6 space-y-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.role === 'assistant' && (
              <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-obd-purple to-obd-accent flex items-center justify-center flex-shrink-0 mt-1">
                <Bot className="w-4 h-4 text-white" />
              </div>
            )}
            <div
              className={`max-w-[70%] ${
                msg.role === 'user'
                  ? 'bg-obd-accent/15 border border-obd-accent/30 rounded-2xl rounded-tr-md'
                  : 'bg-obd-surface border border-obd-border rounded-2xl rounded-tl-md'
              } p-4`}
            >
              <p className="text-sm text-slate-200 leading-relaxed">{msg.content}</p>
              {msg.vehicleDataAccess && (
                <div className="mt-3 pt-3 border-t border-white/5">
                  <div className="flex items-center gap-1.5 text-[11px] text-obd-purple">
                    <Sparkles className="w-3 h-3" />
                    {msg.vehicleDataAccess}
                  </div>
                </div>
              )}
              <span className="text-[10px] text-slate-600 mt-2 block">
                {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
            {msg.role === 'user' && (
              <div className="w-8 h-8 rounded-xl bg-obd-surface-2 flex items-center justify-center flex-shrink-0 mt-1">
                <User className="w-4 h-4 text-slate-400" />
              </div>
            )}
          </div>
        ))}

        {isTyping && (
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-obd-purple to-obd-accent flex items-center justify-center flex-shrink-0">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <div className="bg-obd-surface border border-obd-border rounded-2xl rounded-tl-md p-4">
              <div className="flex gap-1.5">
                <span className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Quick Suggestions */}
      {messages.length <= 1 && (
        <div className="px-6 pb-3">
          <div className="grid grid-cols-2 gap-2">
            {QUICK_SUGGESTIONS.map((s) => (
              <button
                key={s.text}
                onClick={() => { setInput(s.text); }}
                className="flex items-center gap-2 p-3 rounded-xl bg-obd-surface border border-obd-border hover:border-obd-accent/40 text-left text-sm text-slate-400 hover:text-slate-200 transition-all"
              >
                <s.icon className="w-4 h-4 text-obd-accent flex-shrink-0" />
                {s.text}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="p-6 pt-3 border-t border-obd-border">
        <div className="flex gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Ask about your vehicle..."
            className="flex-1 bg-obd-surface border border-obd-border rounded-xl px-4 py-3 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-obd-accent/50 focus:ring-1 focus:ring-obd-accent/25 transition-all"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            className="px-4 py-3 rounded-xl bg-obd-accent text-white hover:bg-obd-accent/90 disabled:opacity-30 disabled:cursor-not-allowed transition-all shadow-lg shadow-obd-accent/20"
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
      </div>
    </div>
  )
}
