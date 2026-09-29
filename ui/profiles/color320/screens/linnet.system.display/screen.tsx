import { Screen, StatusBar, VirtualList, Text } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar w={320} h={28} text="Display" bg="theme.panel" deps={16} />
  <VirtualList x={5} y={32} w={308} h={65} count={2} text="Display timeout" items={['Timeout: 30 seconds','Click: Classic']} focus={true} />
  <Text x={5} y={147} w={308} h={27} text="SELECT/RIGHT Next" fg="theme.muted" />
  <Text x={5} y={180} w={308} h={27} text="LEFT Previous" fg="theme.muted" />
</Screen>
  );
}
