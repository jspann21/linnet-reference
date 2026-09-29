import { Screen, StatusBar, VirtualList, Text } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar w={220} h={20} text="Auto Shutdown" bg="theme.panel" deps={16} />
  <VirtualList x={4} y={24} w={212} h={48} count={2} text="Automatic shutdown" items={['Headphones out: Off','Headphones in: Off']} focus={true} />
  <Text x={4} y={80} w={212} h={20} text="Includes music playback" fg="theme.muted" />
  <Text x={4} y={128} w={212} h={20} text="SELECT/RIGHT Next" fg="theme.muted" />
  <Text x={4} y={152} w={212} h={20} text="LEFT Previous" fg="theme.muted" />
</Screen>
  );
}
