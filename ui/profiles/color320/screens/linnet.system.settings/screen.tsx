import { Screen, StatusBar, Menu, Scrollbar } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar w={320} h={28} text="Settings" bg="theme.panel" deps={16} />
  <Menu x={12} y={36} w={284} h={196} focus={true}
    items={['Display','Video Settings','Themes','Date & Time','Battery','Power','Sleep Timer','USB Disk Mode','Firmware Info','About Linnet','Back to Home','Shuffle: Off','Repeat: Off','Sound']}
    targets={['linnet.system.display','linnet.system.video-settings','linnet.system.themes','linnet.system.clock','linnet.system.battery','linnet.system.shutdown','linnet.system.sleep-timer','@sync','linnet.system.update','linnet.system.about','linnet.system.home','@shuffle','@repeat','linnet.system.music-sound']} />
  <Scrollbar x={306} y={36} w={4} h={196} count={13} fg="theme.accent" />
</Screen>
  );
}
