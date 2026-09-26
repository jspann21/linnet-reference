import { Screen, CanvasSurface, Text } from "@linnet/ui";
export default function Scene() {
  return (<Screen bg="#07162b">
    <CanvasSurface x={0} y={0} w={320} h={240} canvas="linnet.system.game-play.draw" bg="#080429" deps={4} />
    <Text x={12} y={2} w={296} h={20} text="Game title" fg="#ffffff" deps={16} />
    <Text x={12} y={22} w={296} h={18} text="Game score" fg="#8fe8ef" deps={16} />
    <Text x={105} y={93} w={130} h={24} text="Game overlay" fg="#ffffff" deps={16} />
    <Text x={80} y={121} w={180} h={22} text="Game detail" fg="#bfeaf1" deps={16} />
    <Text x={12} y={218} w={296} h={18} text="Game hint" fg="#ffffff" deps={16} />
  </Screen>);
}
