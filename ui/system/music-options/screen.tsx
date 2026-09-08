import { Screen, StatusBar, VirtualList, Scrollbar } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar w={220} h={20} text="Playback options" bg="theme.panel" deps={16} />
  <VirtualList x={4} y={24} w={202} h={148} count={11} text="Option " focus={true} />
  <Scrollbar x={210} y={24} w={6} h={148} count={11} fg="theme.accent" />
</Screen>
  );
}
