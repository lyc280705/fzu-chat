import { CalendarDays, Compass, Sparkles } from 'lucide-react'
import { createElement } from 'react'

const PROMPT_GROUPS = [
  { title: '教务查询', icon: CalendarDays, prompts: ['查询我的成绩', '查询我的课表', '查询我的考场安排'] },
  { title: '校园问答', icon: Compass, prompts: ['福州大学校训是什么', '福州大学最新通知', '旗山校区有哪些食堂'] },
  { title: '个性化', icon: Sparkles, prompts: ['记住我在旗山校区', '查看我的个性化记忆'] },
]

export function EmptyChatState({ onPrompt }) {
  return (
    <div className="empty-state">
      <div className="welcome-brand"><img src="/assets/FZU.png" alt="" /><span>福大灵犀</span></div>
      <h3>开始一次新对话</h3>
      <p>你好呀！我是福大灵犀，你可以向我提问关于福州大学的任何问题，也可以查询你的成绩和课表哦～</p>
      <div className="welcome-groups" aria-label="试试这样问">
        {PROMPT_GROUPS.map(({ title, prompts, icon }) => (
          <section key={title} className="welcome-group" aria-label={title}>
            <div className="welcome-group-heading">
              {createElement(icon, { size: 14, strokeWidth: 1.6, 'aria-hidden': true })}
              <h4>{title}</h4>
            </div>
            <div className="welcome-group-prompts">
              {prompts.map(prompt => (
                <button key={prompt} type="button" className="welcome-prompt" onClick={() => onPrompt(prompt)}>
                  <span>{prompt}</span>
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
