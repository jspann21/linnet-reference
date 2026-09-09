import { Screen, StatusBar, VirtualList, Text } from "@linnet/ui";
export default function Scene() { return (
<Screen>
  <StatusBar w={220} h={20} text="Date & Time" bg="theme.panel" deps={16} />
  <Text x={8} y={30} w={204} h={34} text="System clock" />
  <VirtualList x={4} y={78} w={212} h={48} count={2} text="Clock settings" focus={true}
    items={['Set date and time','Time format: 24-hour']} />
  <Text x={8} y={140} w={204} h={32} text="Clock source" fg="theme.muted" />
</Screen>
); }
