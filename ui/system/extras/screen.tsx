import { Screen, StatusBar, Menu } from "@linnet/ui";
export default function Scene() { return (
<Screen>
  <StatusBar w={220} h={20} text="Extras" bg="theme.panel" deps={16} />
  <Menu x={4} y={24} w={212} h={148} items={['Notes','Videos','Files','UI Demo','About Linnet','Clock']} targets={['linnet.system.notes','linnet.system.videos','linnet.system.files','local.example.notes','linnet.system.about','linnet.system.clock']} focus={true} />
</Screen>
); }
