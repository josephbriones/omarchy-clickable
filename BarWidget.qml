import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.josephbriones.clickable"

  readonly property var clickableService: bar && bar.shell && bar.shell.serviceFor
    ? bar.shell.serviceFor(moduleName)
    : null
  property bool popupOpen: false

  function close() { popupOpen = false }
  function open() {
    popupOpen = true
    Qt.callLater(function() { primaryAction.forceActiveFocus() })
  }
  function togglePopup() { popupOpen ? close() : open() }
  function revealControl(item) {
    if (!item || !item.activeFocus) return
    var point = item.mapToItem(content, 0, 0)
    var top = Math.max(0, point.y - Style.space(8))
    var bottom = point.y + item.height + Style.space(8)
    if (top < contentFlick.contentY) contentFlick.contentY = top
    else if (bottom > contentFlick.contentY + contentFlick.height)
      contentFlick.contentY = Math.min(
        Math.max(0, contentFlick.contentHeight - contentFlick.height),
        bottom - contentFlick.height)
  }

  component AccessButton: Button {
    focusable: true
    bordered: true
    verticalPadding: Math.max(Style.spacing.controlPaddingY, (44 - fontSize) / 2)
    horizontalPadding: Math.max(Style.spacing.controlPaddingX, Style.space(10))
    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.focusable: true
    Accessible.focused: activeFocus
    Accessible.onPressAction: if (enabled) clicked()
    onActiveFocusChanged: if (activeFocus) root.revealControl(this)
  }

  implicitWidth: trigger.implicitWidth
  implicitHeight: barSize

  WidgetButton {
    id: trigger
    bar: root.bar
    text: root.clickableService && root.clickableService.displayAction === "right" ? "R"
      : (root.clickableService && root.clickableService.displayAction === "double" ? "2" : "C")
    fixedWidth: root.vertical ? root.barSize : Math.max(44, root.barSize)
    fixedHeight: root.vertical ? Math.max(44, root.barSize) : root.barSize
    active: !!(root.clickableService && root.clickableService.runningRequested)
    activeColor: root.bar ? root.bar.urgent : Color.urgent
    tooltipText: active
      ? "ClickAble is armed — activate to pause"
      : "ClickAble is paused — activate for controls"
    activeFocusOnTab: true

    Accessible.role: Accessible.Button
    Accessible.name: active
      ? "Pause ClickAble, " + (root.clickableService ? root.clickableService.statusLabel : "starting")
      : "Open ClickAble controls"
    Accessible.description: tooltipText
    Accessible.focusable: true
    Accessible.focused: activeFocus
    Accessible.onPressAction: trigger.triggerPress(Qt.LeftButton)

    Keys.onReturnPressed: trigger.triggerPress(Qt.LeftButton)
    Keys.onEnterPressed: trigger.triggerPress(Qt.LeftButton)
    Keys.onSpacePressed: trigger.triggerPress(Qt.LeftButton)

    onPressed: function(button) {
      if (button === Qt.RightButton) {
        root.togglePopup()
        return
      }
      if (!root.clickableService) return
      if (root.clickableService.runningRequested) {
        root.clickableService.pause("bar")
        root.close()
      } else {
        root.togglePopup()
      }
    }

    Rectangle {
      anchors.fill: parent
      anchors.margins: 2
      z: 2
      visible: trigger.activeFocus
      color: "transparent"
      border.width: 2
      border.color: root.bar ? root.bar.barForeground : Color.foreground
      radius: Style.cornerRadius
    }
  }

  KeyboardPanel {
    id: popup
    anchorItem: root
    bar: root.bar
    owner: root
    open: root.popupOpen
    focusTarget: primaryAction
    contentWidth: popup.fittedContentWidth(Style.space(350))
    contentHeight: popup.fittedContentHeight(content.implicitHeight)

    Flickable {
      id: contentFlick
      anchors.fill: parent
      contentWidth: width
      contentHeight: content.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      Accessible.role: Accessible.Dialog
      Accessible.name: "ClickAble controls"

      Column {
        id: content
        width: contentFlick.width
        spacing: Style.space(10)

      Text {
        width: parent.width
        text: "ClickAble"
        textFormat: Text.PlainText
        color: root.bar ? root.bar.foreground : Color.foreground
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.subtitle
        font.bold: true
        Accessible.role: Accessible.Heading
        Accessible.name: text
      }

      Text {
        width: parent.width
        text: root.clickableService
          ? root.clickableService.statusLabel + " · "
            + Math.round(root.clickableService.dwellMs / 100) / 10 + " second dwell"
          : "Service unavailable"
        textFormat: Text.PlainText
        color: root.bar ? root.bar.foreground : Color.foreground
        opacity: 0.78
        wrapMode: Text.Wrap
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.bodySmall
        Accessible.role: Accessible.StatusBar
        Accessible.name: text
      }

      Text {
        width: parent.width
        visible: !!(root.clickableService && root.clickableService.errorMessage)
        text: visible ? root.clickableService.errorMessage : ""
        textFormat: Text.PlainText
        color: root.bar ? root.bar.urgent : Color.urgent
        wrapMode: Text.Wrap
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.bodySmall
        Accessible.role: Accessible.AlertMessage
        Accessible.name: text
      }

      AccessButton {
        id: primaryAction
        width: parent.width
        foreground: root.bar ? root.bar.foreground : Color.foreground
        accent: root.bar ? root.bar.urgent : Color.urgent
        text: root.clickableService && root.clickableService.runningRequested
          ? "Pause dwell clicking"
          : "Arm dwell clicking"
        leftAlign: true
        enabled: !!(root.clickableService && root.clickableService.settingsLoaded)
        Accessible.role: Accessible.Button
        Accessible.name: text
        Accessible.description: root.clickableService && root.clickableService.runningRequested
          ? "Stops all ClickAble input work immediately. Status: " + root.clickableService.statusLabel
          : "Starts paused-safe dwell clicking; move the pointer once before the first click. Status: "
            + (root.clickableService ? root.clickableService.statusLabel : "unavailable")
        Accessible.focusable: true
        Accessible.focused: activeFocus
        onClicked: {
          if (!root.clickableService) return
          if (root.clickableService.runningRequested) {
            root.clickableService.pause("bar")
            root.close()
          } else {
            root.clickableService.start()
            if (root.clickableService.runningRequested) root.close()
          }
        }
      }

      Text {
        width: parent.width
        text: root.clickableService && root.clickableService.runningRequested
          ? "Move the pointer to rearm. Hold still only when the target is correct."
          : "Nothing clicks until you arm, then move the pointer once."
        textFormat: Text.PlainText
        color: root.bar ? root.bar.foreground : Color.foreground
        opacity: 0.72
        wrapMode: Text.Wrap
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.bodySmall
        Accessible.role: Accessible.StaticText
        Accessible.name: text
      }

      PanelSeparator {
        foreground: root.bar ? root.bar.foreground : Color.foreground
      }

      Text {
        width: parent.width
        text: "Next click"
        textFormat: Text.PlainText
        color: root.bar ? root.bar.foreground : Color.foreground
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.body
        font.bold: true
        Accessible.role: Accessible.Heading
        Accessible.name: text
      }

      Row {
        width: parent.width
        spacing: Style.space(6)

        AccessButton {
          width: (parent.width - parent.spacing * 2) / 3
          text: "Left"
          foreground: root.bar ? root.bar.foreground : Color.foreground
          selected: !!(root.clickableService && root.clickableService.displayAction === "left")
          enabled: !!(root.clickableService && !root.clickableService.sessionLocked
            && (!root.clickableService.runningRequested || root.clickableService.active))
          Accessible.role: Accessible.RadioButton
          Accessible.name: "Left click"
          Accessible.checkable: true
          Accessible.checked: selected
          Accessible.focusable: true
          Accessible.focused: activeFocus
          Accessible.onToggleAction: if (enabled && root.clickableService)
            root.clickableService.setAction("left")
          onClicked: if (root.clickableService) root.clickableService.setAction("left")
        }

        AccessButton {
          width: (parent.width - parent.spacing * 2) / 3
          text: "Right once"
          foreground: root.bar ? root.bar.foreground : Color.foreground
          selected: !!(root.clickableService && root.clickableService.displayAction === "right")
          enabled: !!(root.clickableService
            && !root.clickableService.sessionLocked
            && (!root.clickableService.runningRequested
              || (root.clickableService.active && root.clickableService.supportsAction("right"))))
          Accessible.role: Accessible.RadioButton
          Accessible.name: "Right click once"
          Accessible.description: "Returns to left click after a confirmed click"
          Accessible.checkable: true
          Accessible.checked: selected
          Accessible.focusable: true
          Accessible.focused: activeFocus
          Accessible.onToggleAction: if (enabled && root.clickableService)
            root.clickableService.setAction("right")
          onClicked: if (root.clickableService) root.clickableService.setAction("right")
        }

        AccessButton {
          width: (parent.width - parent.spacing * 2) / 3
          text: "Double once"
          foreground: root.bar ? root.bar.foreground : Color.foreground
          selected: !!(root.clickableService && root.clickableService.displayAction === "double")
          enabled: !!(root.clickableService
            && !root.clickableService.sessionLocked
            && (!root.clickableService.runningRequested
              || (root.clickableService.active && root.clickableService.supportsAction("double"))))
          Accessible.role: Accessible.RadioButton
          Accessible.name: "Double click once"
          Accessible.description: "Returns to left click after a confirmed double click"
          Accessible.checkable: true
          Accessible.checked: selected
          Accessible.focusable: true
          Accessible.focused: activeFocus
          Accessible.onToggleAction: if (enabled && root.clickableService)
            root.clickableService.setAction("double")
          onClicked: if (root.clickableService) root.clickableService.setAction("double")
        }
      }

      Text {
        width: parent.width
        text: "Choose the next click before arming. Right and double return to Left after confirmation; a safety fault also returns to Left."
        textFormat: Text.PlainText
        color: root.bar ? root.bar.foreground : Color.foreground
        opacity: 0.72
        wrapMode: Text.Wrap
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.caption
        Accessible.role: Accessible.StaticText
        Accessible.name: text
      }

      Text {
        width: parent.width
        text: "Dwell delay"
        textFormat: Text.PlainText
        color: root.bar ? root.bar.foreground : Color.foreground
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.body
        font.bold: true
        Accessible.role: Accessible.Heading
        Accessible.name: text
      }

      Row {
        width: parent.width
        spacing: Style.space(6)

        Repeater {
          model: root.clickableService ? root.clickableService.dwellChoices : []

          AccessButton {
            required property int modelData
            width: (parent.width - parent.spacing * 3) / 4
            text: Math.round(modelData / 100) / 10 + " s"
            foreground: root.bar ? root.bar.foreground : Color.foreground
            selected: !!(root.clickableService && root.clickableService.dwellMs === modelData)
            Accessible.role: Accessible.RadioButton
            Accessible.name: text + " dwell delay"
            Accessible.checkable: true
            Accessible.checked: selected
            Accessible.focusable: true
            Accessible.focused: activeFocus
            Accessible.onToggleAction: if (enabled && root.clickableService)
              root.clickableService.setDwellMs(modelData)
            onClicked: if (root.clickableService) root.clickableService.setDwellMs(modelData)
          }
        }
      }

      Text {
        width: parent.width
        text: "Steadiness radius"
        textFormat: Text.PlainText
        color: root.bar ? root.bar.foreground : Color.foreground
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.body
        font.bold: true
        Accessible.role: Accessible.Heading
        Accessible.name: text
      }

      Row {
        width: parent.width
        spacing: Style.space(6)

        Repeater {
          model: root.clickableService ? root.clickableService.toleranceChoices : []

          AccessButton {
            required property int modelData
            width: (parent.width - parent.spacing * 2) / 3
            text: modelData + " px"
            foreground: root.bar ? root.bar.foreground : Color.foreground
            selected: !!(root.clickableService && root.clickableService.tolerancePx === modelData)
            Accessible.role: Accessible.RadioButton
            Accessible.name: modelData + " pixel steadiness radius"
            Accessible.checkable: true
            Accessible.checked: selected
            Accessible.focusable: true
            Accessible.focused: activeFocus
            Accessible.onToggleAction: if (enabled && root.clickableService)
              root.clickableService.setTolerancePx(modelData)
            onClicked: if (root.clickableService) root.clickableService.setTolerancePx(modelData)
          }
        }
      }
      }
    }
  }
}
