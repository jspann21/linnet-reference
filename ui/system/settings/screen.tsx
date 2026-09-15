import { Screen, StatusBar, Menu, Scrollbar } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar w={220} h={20} text="Settings" bg="theme.panel" deps={16} />
  <Menu x={4} y={24} w={202} h={148} focus={true}
    items={['Display','Themes','Clock','Battery','Sync / USB Disk Mode','Update / Recovery','About Linnet','Back to Home']}
    targets={['linnet.system.display','linnet.system.themes','linnet.system.clock','linnet.system.battery','@sync','linnet.system.update','linnet.system.about','linnet.system.home']} />
  <Scrollbar x={210} y={24} w={6} h={148} count={8} fg="theme.accent" />
</Screen>
  );
}
