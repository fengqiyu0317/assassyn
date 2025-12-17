use crate::simulator::Simulator;
use sim_runtime::num_bigint::{BigInt, BigUint};
use sim_runtime::*;
use std::ffi::c_void;

// Elaborating module Driver
pub fn Driver(sim: &mut Simulator) -> bool {
  let cycle_cnt_rd = { sim.cycle_cnt.payload[false as usize].clone() };
  let cycle_cnt_add = { ValueCastTo::<u32>::cast(&cycle_cnt_rd) + ValueCastTo::<u32>::cast(&1u32) };
  // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./assassyn_example.py:79
  {
    let stamp = sim.stamp - sim.stamp % 100 + 50;
    let write = ArrayWrite::new(stamp, false as usize, cycle_cnt_add.clone(), "Driver");
    sim.cycle_cnt.write(0, write);
  };
  let new_test_data = { ValueCastTo::<u64>::cast(&cycle_cnt_rd) * ValueCastTo::<u64>::cast(&3u32) };
  // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./assassyn_example.py:86
  {
    let stamp = sim.stamp - sim.stamp % 100 + 50;
    let write = ArrayWrite::new(stamp, false as usize, new_test_data.clone(), "Driver");
    sim.test_data.write(0, write);
  };
  let cycle_cnt_and = { ValueCastTo::<u32>::cast(&cycle_cnt_rd) & ValueCastTo::<u32>::cast(&1u32) };
  let enable_signal =
    { ValueCastTo::<u32>::cast(&cycle_cnt_and) == ValueCastTo::<u32>::cast(&0u32) };
  let test_data_rd = { sim.test_data.payload[false as usize].clone() };
  let enable_signal_cast = { ValueCastTo::<bool>::cast(&enable_signal) };
  // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./assassyn_example.py:92
  {
    let stamp = sim.stamp;
    sim.DataProcessorInstance_data_in.push.push(FIFOPush::new(
      stamp + 50,
      test_data_rd.clone(),
      "Driver",
    ));
  };
  // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./assassyn_example.py:92
  {
    let stamp = sim.stamp;
    sim.DataProcessorInstance_enable.push.push(FIFOPush::new(
      stamp + 50,
      enable_signal_cast.clone(),
      "Driver",
    ));
  };
  // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./assassyn_example.py:92
  ();
  // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./assassyn_example.py:92
  {
    let stamp = sim.stamp - sim.stamp % 100 + 100;
    sim.DataProcessorInstance_event.push_back(stamp)
  };
  // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./assassyn_example.py:98
  print!("@line:{:<5} {:<10}: [Driver]\t", line!(), cyclize(sim.stamp));
  println!(
    "Driver cycle: {}, test_data: {}, enable: {}",
    cycle_cnt_rd,
    test_data_rd,
    if enable_signal { 1 } else { 0 },
  );

  true
}
