# FZU-Lingxi

[简体中文](README.md)

An intelligent Q&A system for Fuzhou University based on LangGraph and Streamlit.

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.44.0-red.svg)](https://streamlit.io)
[![LangGraph](https://img.shields.io/badge/LangGraph-Latest-green.svg)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)

## Project Introduction

FZU-Lingxi is an intelligent Q&A system designed for the teachers and students of Fuzhou University. It uses RAG technology, combined with the LangGraph workflow and various large language models, to provide users with accurate and timely campus information query services.

### Core Features

- **Multi-model Support**: Integrates mainstream large language models such as Qwen, DeepSeek, and ERNIE Bot.
- **Intelligent Retrieval**: Efficient semantic retrieval based on the FAISS vector database.
- **Real-time Search**: Integrated with the Bocha search engine to obtain the latest information.
- **Friendly Interface**: Modern web interface based on Streamlit.
- **Containerized Deployment**: Supports one-click deployment with Docker.

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- API keys for various AI services

### Docker Deployment (Recommended)

1.  **Clone the project**
    ```bash
    git clone https://github.com/lyc280705/fzu-chat.git
    cd fzu-chat
    ```

2.  **Configure API keys**
    ```bash
    # Create API key files
    echo "your_dashscope_key" > dashscope_api_key.txt
    echo "your_bocha_key" > bocha_api_key.txt
    echo "your_langsmith_key" > langsmith_api_key.txt
    echo "your_deepseek_key" > deepseek_api_key.txt
    echo "your_qianfan_key" > qianfan_api_key.txt
    ```

3.  **Start the service**
    ```bash
    docker compose up -d
    ```

4.  **Access the application**
    ```
    http://localhost:100
    ```

### Local Development

1.  **Install dependencies**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Set environment variables**
    ```bash
    export DASHSCOPE_API_KEY="your_key"
    export BOCHA_API_KEY="your_key"
    export LANGSMITH_API_KEY="your_key"
    export DEEPSEEK_API_KEY="your_key"
    export QIANFAN_API_KEY="your_key"
    ```

3.  **Start the application**
    ```bash
    streamlit run app/app.py
    ```

## Technology Stack

### Backend Framework
- **LangGraph**: Workflow orchestration
- **LangChain**: Large language model integration
- **FAISS**: Vector database
- **SQLite**: Session storage

### Frontend Interface
- **Streamlit**: Web application framework
- **CSS**: Custom styles

### Large Language Models
- **Qwen (Tongyi Qianwen)**: Alibaba Cloud's large model
- **DeepSeek**: DeepSeek model
- **ERNIE Bot (Wenxin Yiyan)**: Baidu's large model

### Deployment Tools
- **Docker**: Containerized deployment
- **Docker Compose**: Service orchestration

## Project Structure

```
fzu-chat/
├── app/
│   ├── app.py              # Main application
│   ├── graph.py            # LangGraph workflow definition
│   ├── data/               # Knowledge base document storage
│   ├── faiss/              # Vector database
│   └── png/                # Static assets
├── docker-compose.yml      # Docker orchestration file
├── Dockerfile             # Docker build file
├── requirements.txt       # Python dependencies
└── README.md             # Project documentation
```

## Configuration

### API Key Configuration

The system requires the following API keys, which can be adjusted as needed:

| Service   | Purpose          | Get it from                                             |
|-----------|------------------|---------------------------------------------------------|
| DashScope | Qwen model       | [Alibaba Cloud Console](https://dashscope.console.aliyun.com/) |
| DeepSeek  | DeepSeek model   | [DeepSeek Platform](https://platform.deepseek.com/)     |
| Qianfan   | ERNIE Bot model  | [Baidu AI Cloud](https://cloud.baidu.com/product/wenxinworkshop) |
| Bocha     | Web search       | [Bocha API](https://bocha.ai/)                          |
| LangSmith | Traceability     | [LangSmith](https://smith.langchain.com/)               |

### Port Configuration

- **Application Port**: 8501 (container) -> 100 (host)
- **Data Volumes**: Persistent storage for knowledge base and session data

## Usage Guide

1.  Enter your question in the input box.
2.  Select a suitable model (Qwen is recommended).
3.  Wait for the system to retrieve relevant information and generate an answer.

## Development Guide

### Adding a New Model

Add the model configuration in `graph.py`. For specific usage, please refer to the LangChain documentation:

```python
# Add a new model client
new_model = ChatNewModel(
    api_key=get_new_model_api_key(),
    model="new-model-name"
)

# Register it in the models dictionary
models = {
    "new-model": new_model,
    # ... other models
}
```

### Expanding the Knowledge Base

1.  Prepare the document data.
2.  Use an embedding model to generate vectors.
3.  Store them in the FAISS vector database.
4.  Update the retriever configuration.

### Custom Tools

Define new tools in `graph.py`:

```python
@tool
def custom_tool(query: str) -> str:
    """Custom tool function"""
    # Implement tool logic
    return result
```

## Open Source License

This project uses a custom license. For details, please refer to the [LICENSE](LICENSE) file.
- **Allowed**: Use for educational and learning purposes.
- **Restricted**: Commercial use, copying, modification, and distribution require mentioning the original authors and retaining the copyright notice.
- **Third-party Components**: Follow their respective original licenses.
- **Special Note**: The copyright of the text segments and school badge icon in the project belongs to Fuzhou University.

## Copyright Information

**© 2024-2025 Lin Yuchen, Zhang Xun, Yuan Hao. All rights reserved.**

### Copyright Ownership

- **Source Code**: Copyright belongs to the project authors.
- **Document Content**: Copyright for content related to Fuzhou University belongs to Fuzhou University.
- **School Badge Logo**: Copyright belongs to Fuzhou University, for educational use only.
- **Third-party Components**: Follow their respective original licenses.

### Citation Format

If you need to cite this project, please use the following format:

```
Yuchen Lin, Xun Zhang, Hao Yuan. (2024-2025). FZU-Lingxi: An intelligent Q&A system for Fuzhou University based on LangGraph and Streamlit.
GitHub: https://github.com/lyc280705/fzu-chat
```

### Disclaimer

This project is provided "as is" without any express or implied warranty. The authors are not liable for any direct or indirect damages arising from the use of this project. Users assume all risks associated with its use.
