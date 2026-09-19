# 日程重叠派生合同

状态：独立功能候选，仅纯前端计算；未接入界面、未发布。不增加 API、数据库字段、云写入或额外授权。

`frontend/src/lib/calendar.ts` 导出：

```ts
type CalendarConflictSpan = { day: string; start: number; end: number; minutes: number };
type CalendarConflict = {
  key: string;
  first: Readonly<CalendarEvent>;
  second: Readonly<CalendarEvent>;
  overlaps: CalendarConflictSpan[];
  minutes: number;
};
calendarConflicts(events: readonly CalendarEvent[], days: readonly string[], focus: string): CalendarConflict[];
```

传入当前身份已授权的 `state.events`、现有 `rangeDays(mode, anchor)` 和关注成员 ID。该函数不能扩大可见范围或判断写入权限：只检查 `owner === focus` 或 `owner === 'shared'` 的日程。因此共同安排与该成员个人安排、两个共同安排可产生重叠；双方各自独立安排不产生该成员的冲突。

返回每对原日程一项。`first`／`second` 是输入的原对象引用，保留原 ID、revision、来源和只读标记，按 ID 字符序排列。`key` 是 `JSON.stringify([first.id, second.id])`，不会因为分隔符、查询顺序、标题或版本改变而歧义或变动。当前 state 应当每个 ID 只有一条记录；若意外重复，使用输入首次出现的记录，不推断哪个版本最新，也不产生自身或重复冲突。

时间继续通过现有 `bounds` 解析，按北京时间的 `dayStart`／`dayKey` 裁剪。过滤不能解析的时间、不存在的日历日期、全天记录及结束不晚于开始的记录。时段使用左闭右开区间，首尾相接不算重叠。所选日期先去重、过滤非标准或不存在的日期，再排序；每个 `overlaps` 只含所选日内的实际交集，`start`／`end` 为毫秒时间戳。跨日的同一对日程仍只返回一项；未选日期不计入 `minutes`。保留小数分钟，展示端自行格式化。

结果按首次重叠开始时间、key 稳定排序；日内片段按日期排序，不修改输入。`result.length` 是重叠日程对数；某日可用 `overlaps.some(span => span.day === day)` 筛选。三条同时发生的日程可形成三对，其分钟数不可相加当作工作量；忙碌总时长继续使用现有 `daySummary`／`rangeSummary` 的区间并集。

界面后续接入：呈现原日程标题、成员和重叠时段；修改前按原 ID 从当前 state 重新定位并复核身份及编辑权限，继续沿原事件编辑／revision 流程。同步来源仍使用既有只读规则。编辑、删除、刷新或切换身份后重新派生；搜索快照和返回对象都不是写入凭证。该模块不负责保存、重试、导航或云同步，也不证明真实账号和实体电视验收。

本地定向验证：`node --test frontend/tests/calendarConflicts.test.mjs tests/test_expo_calendar.mjs`。新测试覆盖成员范围、全天／无效／零时长、北京时间与跨日裁剪、重复日／ID、稳定键与原版本、不变输入、三重重叠和刷新后的消解；旧相邻测试继续检查既有日历语义。
