import { Screen, StatusBar, VirtualList, Text } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar w={220} h={20} text="Display backlight" bg="theme.panel" deps={16} />
  <VirtualList x={4} y={24} w={212} h={32} count={1} text="Display timeout" items={['Timeout: 30 seconds']} focus={true} />
  <Text x={4} y={68} w={212} h={20} text="Battery, USB and AC" fg="theme.muted" />
  <Text x={4} y={108} w={212} h={20} text="Select/right: next" fg="theme.muted" />
  <Text x={4} y={132} w={212} h={20} text="Left: previous" fg="theme.muted" />
</Screen>
  );
}
