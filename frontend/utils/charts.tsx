import { DateTime } from "luxon";

export const formatXAxis = (tickItem: number) => {
  return DateTime.fromSeconds(tickItem).toFormat("yyyy-MM-dd HH:mm");
};

interface DataPoint {
  timestamp: number;
}

export interface AggregatedDataPoint {
  timestamp: number;
  amount: number;
}

export function aggregateData<T extends DataPoint>({
  data,
  bucketSize,
  valueKey,
  transform,
}: {
  data: T[];
  bucketSize: number;
  /** The values under this key must be a number. If the key is omitted each entry will be the value of 1 */
  valueKey?: string;
  /** A function to transform the valueKey */
  transform?: (x: number) => number;
}): AggregatedDataPoint[] {
  const groupedData = data.reduce((acc, curr) => {
    // Create a bucket by truncating the timestamp to the nearest bucketSize.
    const timestamp = Math.floor(curr.timestamp / bucketSize) * bucketSize;

    if (!acc[timestamp]) {
      acc[timestamp] = { timestamp, count: 0 };
      valueKey && (acc[timestamp][valueKey] = 0);
    }

    // It's good to check if curr[valueKey] is a valid number
    valueKey && (acc[timestamp][valueKey] += Number(curr[valueKey]));
    acc[timestamp].count += 1;

    return acc;
  }, {});

  // Convert the grouped data into an array and calculate the average amount.
  const aggregatedData = Object.values(groupedData).map((d: any) => ({
    timestamp: d.timestamp,
    amount: valueKey
      ? d.count > 0
        ? transform
          ? transform(d[valueKey])
          : d[valueKey] / d.count
        : 0 // Protect against division by 0
      : d.count,
  }));
  return aggregatedData;
}
