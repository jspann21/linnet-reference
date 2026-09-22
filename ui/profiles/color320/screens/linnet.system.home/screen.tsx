import { Screen, StatusBar, Scrollbar, Menu } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar x={0} y={0} w={320} h={28} text="Linnet" bg="theme.panel" deps={16} />
  <Menu x={12} y={36} w={284} h={196} focus={true}
    items={['Music','Cover Flow','Photos','Videos','Files','Now Playing','Settings','UI Demo','Notes']}
    targets={['linnet.system.music','linnet.system.cover-flow','linnet.system.photos','linnet.system.videos','linnet.system.files','linnet.system.now-playing','linnet.system.settings','local.example.notes','linnet.system.notes']} />
  <Scrollbar x={306} y={36} w={4} h={196} fg="theme.accent" />
</Screen>
  );
}
