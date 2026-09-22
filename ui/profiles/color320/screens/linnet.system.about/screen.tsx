import { Screen, StatusBar, CanvasSurface, Text } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar w={320} h={28} text="About Linnet" bg="theme.panel" deps={16} />
  <CanvasSurface x={112} y={40} w={96} h={136} canvas="linnet.system.about.emblem" fg="theme.foreground" bg="theme.background" deps={4} />
  <Text x={12} y={184} w={296} h={20} text="LINNET OS" fg="theme.accent" />
  <Text x={12} y={212} w={296} h={20} text="System version and device" fg="theme.muted" />
</Screen>
  );
}
