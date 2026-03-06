"""向后兼容的入口文件（app.py）。

历史上本项目只有一个 app.py 作为入口。
重构后，我们保留 app.py 作为薄封装，避免已有部署脚本/教程失效。

运行：
    python app.py
"""

from tdl_bot.main import main


if __name__ == "__main__":
    main()
