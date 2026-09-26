import { Screen, CanvasSurface, Text, View } from "@linnet/ui";
export default function Scene() {
  return (<Screen bg="#07162b">
    <View x={0} y={0} w={320} h={58} bg="#102c3b" />
    <View x={0} y={204} w={320} h={36} bg="#102c3b" />
    <CanvasSurface x={0} y={58} w={320} h={146} canvas="linnet.system.game-play.draw" bg="#07162b" deps={4} />
    <Text x={12} y={8} w={296} h={22} text="Game title" fg="#ffffff" deps={16} />
    <Text x={12} y={33} w={296} h={20} text="Game score" fg="#8fe8ef" deps={16} />
    <Text x={105} y={93} w={130} h={24} text="Game overlay" fg="#ffffff" deps={16} />
    <Text x={80} y={121} w={180} h={22} text="Game detail" fg="#bfeaf1" deps={16} />
    <Text x={12} y={212} w={296} h={20} text="Game hint" fg="#ffffff" deps={16} />
  </Screen>);
}
