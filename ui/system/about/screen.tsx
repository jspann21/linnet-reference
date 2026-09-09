import { Screen, StatusBar, View, Text, Image } from "@linnet/ui";
export default function Scene() {
  return (
<Screen>
  <StatusBar w={220} h={20} text="About Linnet" bg="theme.panel" deps={16} />
  <View x={8} y={28} w={204} h={136} bg="theme.panel" flags={4}>
    <Image x={8} y={8} w={32} h={32} resource="artwork" />
    <Text x={48} y={8} w={148} h={28} text="Linnet 0.1" />
    <Text x={8} y={50} w={188} h={24} text="Music, photos and more" />
    <Text x={8} y={82} w={188} h={34} text="iPod Photo" fg="theme.muted" />
  </View>
</Screen>
  );
}
