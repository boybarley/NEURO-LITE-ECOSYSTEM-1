# NEURO-LITE ECOSYSTEM

NEURO-LITE is a lightweight conversational AI system designed to run on constrained hardware. It provides professional, empathetic responses while optimizing for low resource usage.

## Overview

- **Hardware Target:** Ubuntu 22.04 LTS with 4GB RAM, Intel i3 CPU (No GPU required)
- **Core Model:** Qwen2.5-3B-Instruct (4-bit quantized)
- **Features:**
  - Responsive, empathetic conversations
  - Knowledge retrieval without embeddings
  - Memory-efficient design
  - Professional formatting

## Quick Installation

```bash
# 1. Clone the repository
git clone https://github.com/boybarley/NEURO-LITE-ECOSYSTEM-1.git
cd NEURO-LITE-ECOSYSTEM-1

# 2. Run the installer (requires sudo)
sudo ./install.sh
```

The installer will automatically:
- Tune OS settings for optimal performance
- Install required dependencies
- Download the model
- Set up a systemd service

## Post-Installation

Once installation is complete, the service will start automatically.

- **Web Interface:** http://localhost:8000
- **Service Status:** `sudo systemctl status neuro-lite`
- **View Logs:** `sudo journalctl -u neuro-lite`
- **Control Script:** `neuro-lite-ctl [status|start|stop|restart|logs|config]`

## Requirements

- Ubuntu 22.04 LTS (or compatible)
- 4GB RAM minimum
- At least 3GB free disk space
- Internet connection for installation

## Configuration

The main configuration file is located at `/opt/neuro-lite/config.env`. You can edit it with:

```bash
sudo neuro-lite-ctl config
```

Remember to restart the service after making changes:

```bash
sudo neuro-lite-ctl restart
```

## Adding Knowledge

The system uses a SQLite database for knowledge retrieval. To add knowledge:

1. Use the provided developer tools:

```bash
cd tools
python3 distill_knowledge.py --api-key YOUR_API_KEY --topic "Your Topic" --db-path /opt/neuro-lite/data/knowledge.db
```

2. Or manually add entries to the database using SQLite.

## Troubleshooting

If you encounter issues:

1. **Service won't start:**
   - Check logs with `sudo journalctl -u neuro-lite -n 50`
   - Ensure the model was downloaded correctly

2. **Slow responses:**
   - Check system load with `htop`
   - Consider reducing `THREADS` in config.env

3. **Out of memory:**
   - Ensure swap space is enabled
   - Check memory usage with `free -h`

## System Architecture

NEURO-LITE uses a single-pass architecture:
- Frontend web interface using HTML/JS/CSS
- FastAPI backend with streaming response
- llama.cpp for efficient inference
- SQLite FTS5 for knowledge retrieval
- String-based post-processing for empathy

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- [llama.cpp](https://github.com/ggerganov/llama.cpp) for efficient inference
- [FastAPI](https://fastapi.tiangolo.com/) for the API server
- [Qwen2.5](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct) model from Alibaba

---

For more information or support, open an issue on GitHub or contact the maintainers.
