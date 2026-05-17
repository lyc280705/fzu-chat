const QUICK_PROMPT_GROUPS = [
  {
    title: '教务查询',
    prompts: ['查询我的成绩', '查询我的课表', '查询我的考场安排'],
  },
  {
    title: '校园问答',
    prompts: ['福州大学校训是什么', '福州大学最新通知', '旗山校区有哪些食堂'],
  },
  {
    title: '个性化',
    prompts: ['记住我喜欢简洁回答', '查看我的个性化记忆'],
  },
]

export function EmptyChatState({ message, onPrompt }) {
  return (
    <div className="empty-state">
      <img src="/assets/FZU.png" alt="福州大学" className="empty-logo" />
      <h3>开始一次新对话</h3>
      <p>{message}</p>
      <div className="quick-action-groups">
        {QUICK_PROMPT_GROUPS.map((group) => (
          <section key={group.title} className="quick-action-group" aria-label={group.title}>
            <span>{group.title}</span>
            <div className="quick-actions">
              {group.prompts.map((prompt) => (
                <button key={prompt} type="button" onClick={() => onPrompt(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
