import webui

bridge = webui.JavaScriptBridge()
window = webui.WebviewWindow(bridge)
window.run(debug=True)