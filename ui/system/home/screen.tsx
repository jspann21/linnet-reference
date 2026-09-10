import { Screen, StatusBar, Menu } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar x={0} y={0} w={220} h={20} text="Linnet" bg="theme.panel" deps={16} />
  <Menu x={4} y={24} w={212} h={148} focus={true}
    items={['Music','Photos','Videos','Files','Now Playing','Settings','UI Demo']}
    targets={['linnet.system.music','linnet.system.photos','linnet.system.videos','linnet.system.files','linnet.system.now-playing','linnet.system.settings','local.example.notes']} />
</Screen>
  );
}
