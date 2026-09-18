import { Screen, StatusBar, Scrollbar, Menu } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar x={0} y={0} w={220} h={20} text="Linnet" bg="theme.panel" deps={16} />
  <Menu x={4} y={24} w={202} h={148} focus={true}
    items={['Music','Cover Flow','Photos','Videos','Files','Now Playing','Settings','UI Demo','Notes']}
    targets={['linnet.system.music','linnet.system.cover-flow','linnet.system.photos','linnet.system.videos','linnet.system.files','linnet.system.now-playing','linnet.system.settings','local.example.notes','linnet.system.notes']} />
  <Scrollbar x={210} y={24} w={6} h={148} fg="theme.accent" />
</Screen>
  );
}
