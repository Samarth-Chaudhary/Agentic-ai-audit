# AWS Lambda Packaging & Dependency Strategy

## Architectural Evaluation: Container Image vs. ZIP Packaging

This document records the architectural decision regarding packaging dependencies for the AI Agent Governance & Audit Lambda functions.

---

### 1. Analysis of Dependency Footprint

The audit pipeline incorporates three analytical governance controls:
1. **Scope Violation Control**: Pure Python AST/JSON rule engine.
2. **Sensitive Data / PII Control**: Microsoft Presidio Analyzer & Anonymizer backed by spaCy NLP (`en_core_web_sm`).
3. **Factual Groundedness Control**: Sentence Transformers (`all-MiniLM-L6-v2`) and NLI Cross-Encoder (`cross-encoder/nli-deberta-v3-small`) backed by PyTorch (`torch`) and Hugging Face Transformers.

#### Package Size Breakdown (Uncompressed)
| Component | Package / Assets | Size on Disk |
| :--- | :--- | :--- |
| PyTorch (`torch`) | CUDA-stripped CPU wheel | ~750 MB |
| Hugging Face Transformers | `transformers`, `tokenizers`, `huggingface-hub` | ~120 MB |
| spaCy & Models | `spacy`, `en_core_web_sm` | ~60 MB |
| Presidio | `presidio-analyzer`, `presidio-anonymizer` | ~25 MB |
| Sentence Transformers | `sentence-transformers` | ~35 MB |
| Core Framework | `boto3`, `pydantic`, `jsonschema`, `pyyaml` | ~45 MB |
| **Total Dependencies** | | **~1,035 MB (>1.0 GB)** |

---

### 2. Constraint Comparison

| Evaluation Metric | Standard ZIP + Lambda Layers | ECR Container Image |
| :--- | :--- | :--- |
| **Maximum Uncompressed Size** | **250 MB** (Hard limit) | **10 GB** |
| **Model Pre-caching** | Requires runtime downloads from HuggingFace to `/tmp` (cold start > 45s) | Pre-baked into Docker image layers (zero network download) |
| **Reproducibility** | Fragile across OS glibc versions (Amazon Linux 2/2023 vs Windows/macOS) | Deterministic Multi-stage build on `public.ecr.aws/lambda/python:3.11` |
| **Startup / Cold Start** | High latency on model fetch | Fast startup with cached PyTorch & spaCy weights in container filesystem |

---

### 3. Architectural Decision: Container Strategy for Audit Lambda

1. **Audit Lambda (`lambda/audit_handler.py`)**:
   - **Strategy**: **Container Image (`Dockerfile.lambda`) deployed via Amazon ECR**.
   - **Rationale**: The ML/NLP dependencies exceed the 250MB Lambda ZIP limit by a factor of 4. Container images allow PyTorch, spaCy language models, and transformer model weights to be baked into the image. This guarantees deterministic, network-isolated inference without runtime downloading or external dependency risks.

2. **Read Lambdas (`lambda/list_traces.py` & `lambda/get_trace.py`)**:
   - **Strategy**: **Standard Lightweight ZIP package (or minimal container)**.
   - **Rationale**: Read Lambdas only use `boto3` (included in AWS Lambda runtime), standard library modules, and lightweight regex redactions. They can cold start in <200ms with a package size under 1MB.
