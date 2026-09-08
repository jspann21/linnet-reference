import { Screen, StatusBar, Grid, Text } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar w={220} h={20} text="Photos" bg="theme.panel" deps={16} />
  <Grid x={4} y={24} w={212} h={148} count={0} text="Photos" focus={true} />
  <Text x={8} y={72} w={204} h={36} text="Photo empty folder" />
</Screen>
  );
}
