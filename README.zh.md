# 福大灵犀

[简体中文](README.zh.md) | [English](README.md)

基于 LangGraph 和 Streamlit 的福州大学智能问答系统

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.44.0-red.svg)](https://streamlit.io)
[![LangGraph](https://img.shields.io/badge/LangGraph-Latest-green.svg)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)

## 项目简介

福大灵犀是一个专为福州大学师生打造的智能问答系统，采用RAG技术，结合 LangGraph工作流和多种大语言模型，为用户提供准确、及时的校园信息查询服务。

### 核心特性

- **多模型支持**：集成通义千问、DeepSeek、文心一言等主流大语言模型
- **智能检索**：基于 FAISS 向量数据库的高效语义检索
- **实时搜索**：集成博查搜索引擎，获取最新信息
- **友好界面**：基于 Streamlit 的现代化 Web 界面
- **容器化部署**：支持 Docker 一键部署


## 快速开始

### 环境要求

- Python 3.12+
- Docker & Docker Compose
- 各 AI 服务 API 密钥

### Docker 部署（推荐）

1. **克隆项目**
   ```bash
   git clone https://github.com/lyc280705/fzu-chat.git
   cd fzu-chat
   ```

2. **配置 API 密钥**
   ```bash
   # 创建 API 密钥文件
   echo "your_dashscope_key" > dashscope_api_key.txt
   echo "your_bocha_key" > bocha_api_key.txt
   echo "your_langsmith_key" > langsmith_api_key.txt
   echo "your_deepseek_key" > deepseek_api_key.txt
   echo "your_qianfan_key" > qianfan_api_key.txt
   ```

3. **启动服务**
   ```bash
   docker compose up -d
   ```

4. **访问应用**
   ```
   http://localhost:100
   ```

### 本地开发

1. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

2. **设置环境变量**
   ```bash
   export DASHSCOPE_API_KEY="your_key"
   export BOCHA_API_KEY="your_key"
   export LANGSMITH_API_KEY="your_key"
   export DEEPSEEK_API_KEY="your_key"
   export QIANFAN_API_KEY="your_key"
   ```

3. **启动应用**
   ```bash
   streamlit run app/app.py
   ```

## 技术栈

### 后端框架
- **LangGraph**: 工作流编排
- **LangChain**: 大语言模型集成
- **FAISS**: 向量数据库
- **SQLite**: 会话存储

### 前端界面
- **Streamlit**: Web 应用框架
- **CSS**: 自定义样式

### 大语言模型
- **通义千问 (Qwen)**: 阿里云大模型
- **DeepSeek**: 深度求索模型
- **文心一言**: 百度大模型

### 部署工具
- **Docker**: 容器化部署
- **Docker Compose**: 服务编排

## 项目结构

```
fzu-chat/
├── app/
│   ├── app.py              # 主应用程序
│   ├── graph.py            # LangGraph 工作流定义
│   ├── data/               # 知识库文档存储
│   ├── faiss/              # 向量数据库
│   └── png/                # 静态资源
├── docker-compose.yml      # Docker 编排文件
├── Dockerfile             # Docker 构建文件
├── requirements.txt       # Python 依赖
└── README.md             # 项目文档
```

## 配置说明

### API 密钥配置

系统需要以下 API 密钥，可以根据需要调整：

| 服务 | 用途 | 获取地址 |
|------|------|----------|
| DashScope | 通义千问模型 | [阿里云控制台](https://dashscope.console.aliyun.com/) |
| DeepSeek | DeepSeek 模型 | [DeepSeek 平台](https://platform.deepseek.com/) |
| Qianfan | 文心一言模型 | [百度智能云](https://cloud.baidu.com/product/wenxinworkshop) |
| Bocha | 网络搜索 | [博查 API](https://bocha.ai/) |
| LangSmith | 链路追踪 | [LangSmith](https://smith.langchain.com/) |

### 端口配置

- **应用端口**: 8501 (容器内) -> 100 (主机)
- **数据卷**: 知识库和会话数据持久化存储

## 使用指南

1. 在输入框中输入问题
2. 选择合适的模型（通义千问推荐）
3. 等待系统检索相关信息并生成回答

## 开发指南

### 添加新的模型

在 `graph.py` 中添加模型配置，具体用法请查阅LangChain文档：

```python
# 添加新的模型客户端
new_model = ChatNewModel(
    api_key=get_new_model_api_key(),
    model="new-model-name"
)

# 在模型字典中注册
models = {
    "new-model": new_model,
    # ... 其他模型
}
```

### 扩展知识库

1. 准备文档数据
2. 使用 embedding 模型生成向量
3. 存储到 FAISS 向量数据库
4. 更新检索器配置

### 自定义工具

在 `graph.py` 中定义新的工具：

```python
@tool
def custom_tool(query: str) -> str:
    """自定义工具函数"""
    # 工具逻辑实现
    return result
```

## 开源协议

本项目采用自定义许可证。详细信息请参阅 [LICENSE](LICENSE) 文件。
- **允许**：教育和学习目的使用
- **限制**：商业用途、复制、修改和分发需提及原始作者并保留版权声明
- **第三方组件**：遵循各自原有许可证
- **特别说明**：项目中的文本分段及校徽图标版权归属福州大学

## 版权信息

**© 2024-2025 林昱辰、章勋、袁浩。版权所有。**

### 版权归属

- **源代码**：版权归项目作者所有
- **文档内容**：福州大学相关内容版权归福州大学所有
- **校徽标识**：版权归福州大学所有，仅限教育用途使用
- **第三方组件**：遵循各自原有许可证

### 引用格式

如需引用本项目，请使用以下格式：

```
林昱辰, 章勋, 袁浩. (2024-2025). 福大灵犀: 基于LangGraph和Streamlit的福州大学智能问答系统. 
GitHub: https://github.com/lyc280705/fzu-chat
```

### 免责声明

本项目按"现状"提供，不提供任何明示或暗示的担保。作者不承担因使用本项目而产生的任何直接或间接损失责任。使用者应自行承担使用风险。