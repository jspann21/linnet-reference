import { Screen, StatusBar, Menu } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar w={220} h={20} text="Settings" bg="theme.panel" deps={16} />
  <Menu x={4} y={24} w={212} h={148} focus={true}
    items={['Sync / USB Disk Mode','About Linnet','Back to Home','Display','Battery','Update / Recovery','Themes','Clock']}
    targets={['@sync','linnet.system.about','linnet.system.home','linnet.system.display','linnet.system.battery','linnet.system.update','linnet.system.themes','linnet.system.clock']} />
</Screen>
  );
}
