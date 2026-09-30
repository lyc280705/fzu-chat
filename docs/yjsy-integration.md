# 研究生教务接入

参考版本固定为 [west2-online/yjsy v0.0.11](https://github.com/west2-online/yjsy/tree/v0.0.11)，提交 `d6180deb704c465e4572b62d6c9f505ab0cd3289`。仅实现该版本已有的登录、成绩、学期/课表、学生信息和考场查询。未查询或使用任何第三方学生账号。

## 请求与解析映射

| 参考源码 | 本地入口 | 保持一致的协议和字段 |
| --- | --- | --- |
| `user.go: Login` | `YjsyClient.login` | 直接 POST `/login.aspx`；表单仅 `muser`、UTF-8 Base64 `passwd`；Referer `https://yjsy.fzu.edu.cn/`、Origin `https://yjsy.fzu.edu.cn`；相同 User-Agent；不跟随重定向；保留 `Path=/` 的 Cookie。无需本科验证码、MD5、SSO 或 `id` 参数。 |
| `user.go: CheckSession`、`yjsy.go: GetWithIdentifier` | `validate_session`、`_get` | 读取成绩页判断会话；识别 HTTP 200 中的“当前登录用户已过期”和“系统发生错误”。 |
| `mark.go: GetMarks` | `get_marks` | `/cjgl/xs_cjcx.aspx`；第二个 `align=center` 表格，第 7 行起；零基列 1/2/3/5/6 对应课程名、修读类别、学期、学分、成绩。不生成 GPA。 |
| `course.go: GetTerms` | `get_terms` | `/xqxk/kbcx_list.aspx?page=1&pageSize=1000`；`divContent` 表格去表头，第一列为学期；跳过首格带 colspan 的提示行，去重后字符串降序排列。包括 v0.0.11 新生无课程修复。 |
| `course.go: GetSemesterCourses` | `get_courses` | `/xqxk/kbcx_list.aspx`，首请求 `strwhere=XNXQ='<原始学期>'`；随后跟随 `divPage` 中“下一页”的 href。零基列 0/2/5/6/7/8 对应学期、课程名、教师、时间地点、授课计划链接、备注。课程学分保持空值。 |
| `course.go: parseScheduleRules` | `_schedule_rules` | 按 `1-8周 星期3:9-11节 东3-109` 格式解析周次、星期、节次和地点，多行分别解析；单双周标记均为 true，与参考版本相同。 |
| `info.go` | `get_student_info` | `#xxTable > table`；一基行列：(1,2)学号、(1,4)姓名、(3,4)生日、(2,4)性别、(15,2)学院、(14,4)年级、(15,4)专业。 |
| `room.go` | `get_exam_rooms` | `/ksgl/kscx.aspx`，`strwhere=XNXQ='<原始学期>'`；`divContent` 表格去表头，零基列 1/4/5 对应课程名、日期时间、地点；日期前两处 `/` 转 `-`，教师与学分留空。 |

研究生原始学期值直接用于请求和展示，不转换为本科系统的六位学期码。用户可使用工具返回的完整学期名称，或“本学期/上学期”；默认选择最近有课表记录的学期，不声称它一定是当前自然学期。成绩筛选使用独立的原始学期匹配；未匹配的明确学期返回未找到，不伪造数据。

## 本地适配与防御性差异

以下是明确的本地适配，不宣称与 Go SDK 每一行实现或全部异常行为相同：

- 维持项目的 TLS 证书校验，不复制 SDK 的 `InsecureSkipVerify`；如有自定义可信 CA，使用 `FZU_CHAT_YJSY_CA_BUNDLE`。
- 登录成功必须同时收到重定向与非空、根路径的 `.ASPXAUTH`。网络错误、只有匿名 Session Cookie、HTTP 200 登录失败页都不会建立已认证会话。
- 不自动重试登录。初次登录与重连共用账号级限额（30 分钟最多 5 次，包含成功尝试），避免上游注释提及的连续失败锁定。
- 给网络请求加超时；限制分页为同源 HTTPS，拒绝循环分页和超过 100 个后续页的异常结果。
- 对短行、缺失日期时间、未知表格结构做边界检查，避免参考实现直接索引导致崩溃。未知表格结构报错，不当作成功查到空数据。
- 学生信息将相同单元格的内容转换为纯文本，供现有工具卡片展示；SDK 返回的是单元格 HTML。课程时间同时保留原文和对应解析结果。
- 输出键名映射到本项目工具契约，并附加 `student_type=graduate`，让成绩卡片隐藏未提供的绩点、课表卡片隐藏未提供的学分。不会从本科公式补算。
- 单次工具查询中复用已获取的学期列表。模型只绑定四个有上游实现的查询工具；本科选课确认接口仍只接受本科身份。
- 本地账号 ID 为 `graduate:<学号>`，上游登录仍使用原始学号。本科 ID 和已有存储路径不变；会话、对话、Passkey 和缓存按本地身份隔离。公开返回 `student_id` 供界面显示。
- 研究生暂不启用本科教务自动提醒，校园生活推荐不会把研究生 Cookie 发给本科系统。

## 验证范围

`tests/test_yjsy_client.py` 使用根据上述源码字段位置构造的合成 HTML，逐项验证请求参数、Cookie 路径、过期/错误识别、成绩列、空学期、分页、课表、个人信息和考试字段。`tests/test_graduate_integration.py` 验证本地登录接口到会话、工具、模型绑定的链路，以及跨身份隔离、多设备重连和过期清理。所有学校 HTTP 和模型调用均为模拟，意外联网直接失败。

这些测试未运行原始 Go SDK，也没有真实研究生登录后的 HTML 样本。公开登录页和未登录查询页可用，只能验证公网连接和未授权响应，不能证明认证成功或生产解析正确。真实账号首次联调仍需验证：成功登录 Cookie、完整课表分页、不同学期、空数据、成绩与考场字段、会话过期及重连。

运行方式：

```sh
python -m pytest -q tests/test_yjsy_client.py tests/test_graduate_integration.py
```

需使用安装了项目 `requirements.txt` 的 Python 环境。

2026-09-30 本地验证：研究生协议/集成、本科解析、会话与多设备同步、访客、选课确认、校园推荐的相关测试合计 95 项通过；前端 lint、生产构建通过。浏览器确认原登录类型文字位置的紧凑下拉框可切换本科生和研究生；未进行真实账号登录。测试环境在继承 `langchain` 环境的临时 venv 中补齐了项目已声明的 `webauthn==3.0.0`，未改动原 Conda 环境。
