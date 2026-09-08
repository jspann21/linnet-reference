import { Screen, StatusBar, Text } from "@linnet/ui";
export default function Scene() { return (
<Screen>
  <StatusBar w={220} h={20} text="Clock" bg="theme.panel" deps={16} />
  <Text x={56} y={62} w={130} h={34} text="System clock" />
  <Text x={28} y={112} w={180} h={24} text="Clock source" fg="theme.muted" />
  <Text x={8} y={150} w={204} h={24} text="Select: set date/time" fg="theme.muted" />
</Screen>
); }
