import { Screen, StatusBar, Scrollbar, Grid, Text } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar w={320} h={28} text="Photos" bg="theme.panel" deps={16} />
  <Grid x={12} y={36} w={284} h={196} count={0} text="Photos" focus={true} />
  <Text x={8} y={24} w={304} h={24} text="Photo count" />
  <Text x={11} y={98} w={296} h={49} text="Photo empty folder" />
  <Scrollbar x={306} y={36} w={4} h={196} fg="theme.accent" />
</Screen>
  );
}
