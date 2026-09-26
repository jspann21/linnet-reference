import { Screen, CanvasSurface, Text } from "@linnet/ui";
export default function Scene() {
  return (<Screen bg="#07162b">
    <CanvasSurface x={0} y={0} w={220} h={176} canvas="linnet.system.game-play.draw" bg="#07162b" deps={4} />
    <Text x={7} y={5} w={206} h={20} text="Game title" fg="#ffffff" deps={16} />
    <Text x={7} y={28} w={206} h={18} text="Game score" fg="#8fe8ef" deps={16} />
    <Text x={63} y={76} w={120} h={20} text="Game overlay" fg="#ffffff" deps={16} />
    <Text x={46} y={101} w={170} h={18} text="Game detail" fg="#bfeaf1" deps={16} />
    <Text x={7} y={153} w={206} h={18} text="Game hint" fg="#ffffff" deps={16} />
  </Screen>);
}
