// Parametral panel — Plasma betik (evaluateScript) sürümü.
//
// Look-and-feel içindeki layout dosyası yalnızca "tema uygula" yolunda çalışıyor;
// yeni bir profilde Plasma paneli hiç kurmayabiliyor (masaüstü çıplak kalır,
// başlat menüsü olmaz). Bu dosya paneli doğrudan kurar.
//
// autohide YOK: kullanıcı çubuğu görmeli. Gizlenen çubuk "panel yok" gibi görünüyor.

var panel = new Panel("org.kde.plasma.panel")

panel.location = "bottom"
panel.height = 48
panel.hiding = "normal"

var launcher = panel.addWidget("org.kde.plasma.kickoff")
// Başlat menüsü düğmesi bizim logomuz olsun (v0.1.23).
launcher.currentConfigGroup = ["Configuration", "General"]
launcher.writeConfig("icon", "parametral-start")
panel.addWidget("org.kde.plasma.icontasks")
panel.addWidget("org.kde.plasma.marginsseparator")
panel.addWidget("org.kde.plasma.systemtray")
panel.addWidget("org.kde.plasma.digitalclock")
