import { Screen, StatusBar, VirtualList, Text } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar w={220} h={20} text="Display" bg="theme.panel" deps={16} />
  <VirtualList x={4} y={24} w={212} h={48} count={2} text="Display timeout" items={['Backlight: 30 sec','Themes']} focus={true} />
  <Text x={4} y={108} w={212} h={20} text="SELECT/RIGHT Next" fg="theme.muted" />
  <Text x={4} y={132} w={212} h={20} text="LEFT Previous" fg="theme.muted" />
</Screen>
  );
}
