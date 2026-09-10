import { Screen, StatusBar, CanvasSurface, Text } from "@linnet/ui";
export default function Scene() {
  return (
    <Screen>
      <StatusBar w={220} h={20} text="About Linnet" bg="theme.panel" deps={16} />
      <CanvasSurface x={76} y={28} w={68} h={104} canvas="linnet.system.about.emblem" fg="theme.foreground" bg="theme.background" deps={4} />
      <Text x={8} y={136} w={204} h={14} text="LINNET OS" fg="theme.accent" />
      <Text x={8} y={156} w={204} h={14} text="0.1.0 / iPod Photo" fg="theme.muted" />
    </Screen>
  );
}
