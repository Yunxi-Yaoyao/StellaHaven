export const TEMPLATE_TAG = '模板';
export const builtinTemplates = [
  { id: 'blank', title: '空白文章', description: '从空白正文开始。', content: '' },
  { id: 'article', title: '文章模板', description: '摘要、结论、原理、操作与验证。', content: '> 摘要：填写本文主题和适用场景。\n\n## 核心结论\n\n\n## 原理与概念\n\n\n## 操作或示例\n\n\n## 验证结果\n\n\n## 关联阅读\n\n\n## 参考资料\n\n\n## 待办\n\n- [ ] 补充并验证内容\n' },
  { id: 'event', title: '事件记录模板', description: '影响、时间线、定位、处理、验证与回滚。', content: '> 时间：\n> 环境：\n> 状态：待确认\n\n## 现象与影响\n\n\n## 时间线\n\n| 时间 | 事件与证据 |\n| --- | --- |\n| | |\n\n## 定位与根因\n\n\n## 处理过程\n\n\n## 验证结果\n\n- [ ] 功能恢复\n- [ ] 日志与监控确认\n\n## 回滚方案\n\n\n## 后续行动\n\n- [ ] \n\n## 参考与关联\n\n' },
] as const;
