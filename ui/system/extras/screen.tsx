import { Screen, StatusBar, Menu } from "@linnet/ui";
export default function Scene() { return (
<Screen>
  <StatusBar w={220} h={20} text="Extras" bg="theme.panel" deps={16} />
  <Menu x={4} y={24} w={212} h={148} items={['Clock','Notes','Videos','Files','UI Demo']} targets={['linnet.system.clock','linnet.system.notes','linnet.system.videos','linnet.system.files','local.example.notes']} focus={true} />
</Screen>
); }
