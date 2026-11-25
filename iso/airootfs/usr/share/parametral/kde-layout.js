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

panel.addWidget("org.kde.plasma.kickoff")
panel.addWidget("org.kde.plasma.icontasks")
panel.addWidget("org.kde.plasma.marginsseparator")
panel.addWidget("org.kde.plasma.systemtray")
panel.addWidget("org.kde.plasma.digitalclock")
